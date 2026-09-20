import copy
import io
import json
from threading import Event
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlmodel import Session

from app.agent.attachments import prepare_attachment, attach_content, responses_content
from app.agent.context import total_tokens, compact_history
from app.agent.loop import run_agent
from app.db.engine import get_engine
from app.models import Model, Provider
from app.providers.client import ToolCall, ToolTurn


def image_bytes():
    output = io.BytesIO()
    Image.new('RGB', (100, 80), 'red').save(output, 'PNG')
    return output.getvalue()


def seed():
    with Session(get_engine()) as s:
        p = Provider(name='test', type='openai_compat')
        s.add(p); s.commit(); s.refresh(p)
        image = Model(provider_id=p.id, model_id='vision', supports_images=True)
        text = Model(provider_id=p.id, model_id='text-only', supports_images=False, role_default='chat')
        s.add(image); s.add(text); s.commit(); s.refresh(image); s.refresh(text)
        return image.id, text.id


def test_clipboard_image_normalized_and_budget_does_not_count_base64():
    attachment = prepare_attachment('截图.png', image_bytes()).model_dump()
    content = attach_content('看图', [attachment])
    assert content[-1]['image_url']['url'].startswith('data:image/png;base64,')
    assert 4096 < total_tokens([{'role': 'user', 'content': content}]) < 4200
    converted = responses_content(content)
    assert converted[-1]['type'] == 'input_image'
    assert converted[0] == {'type': 'input_text', 'text': '看图'}


@pytest.mark.parametrize('name,raw,expected', [('notes.md', '# 研究材料'.encode(), '研究材料'),
    ('结果.csv', '方法,结果\nA,42'.encode('gb18030'), 'A,42')])
def test_text_upload(client, name, raw, expected):
    response = client.post('/api/chat/attachments', files={'file': (name, raw)})
    assert response.status_code == 200
    assert expected in response.json()['text']


def test_pdf_and_docx_extract():
    import pymupdf
    import zipfile
    doc = pymupdf.open(); page = doc.new_page(); page.insert_text((20, 40), 'Experiment accuracy 93.2%')
    assert '93.2%' in prepare_attachment('paper.pdf', doc.tobytes()).text
    doc.close()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Word result 42</w:t></w:r></w:p></w:body></w:document>')
    assert 'Word result 42' in prepare_attachment('results.docx', output.getvalue()).text


@pytest.mark.parametrize('name,raw', [('empty.txt', b''), ('huge.txt', b'a'*60001), ('bad.png', b'not an image'), ('archive.zip', b'123')], ids=['empty','too-long','bad-image','unsupported'])
def test_unreadable_upload_explained(client, name, raw):
    response = client.post('/api/chat/attachments', files={'file': (name, raw)})
    assert response.status_code == 422
    assert response.json()['detail']


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_attachment_reaches_model_and_history_and_retry(client, monkeypatch, suffix):
    vision, _ = seed()
    item = client.post('/api/chat/attachments', files={'file': ('截图.png', image_bytes())}).json()
    cid = client.post('/api/chat/conversations').json()['id']
    calls = []
    def complete(self, provider, model, messages, *args, **kwargs):
        calls.append((model, copy.deepcopy(messages)))
        if len(calls) == 1:
            raise TimeoutError('synthetic timeout')
        return ToolTurn('图片已收到', [], 1, 1, 2)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', complete)
    client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'attachments': [item], 'model_config_id': vision})
    history = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert history[0]['attachments'] == [item]
    assert history[0]['retryable']
    response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': history[0]['content'], 'retry_message_id': history[0]['id']})
    assert response.status_code == 200
    assert calls[0] == calls[1]
    assert calls[1][0] == 'vision'
    assert calls[1][1][-1]['content'][-1]['type'] == 'image_url'
    assert len(client.get(f'/api/chat/conversations/{cid}').json()['messages']) == 2


def test_text_model_rejection_does_not_persist_empty_turn(client):
    _, text = seed()
    cid = client.post('/api/chat/conversations').json()['id']
    item = prepare_attachment('image.png', image_bytes()).model_dump()
    response = client.post(f'/api/chat/conversations/{cid}/messages', json={'attachments': [item], 'model_config_id': text})
    assert response.status_code == 422
    assert client.get(f'/api/chat/conversations/{cid}').json()['messages'] == []


def test_stop_before_tools_prevents_side_effects(monkeypatch):
    stop = Event()
    executed = []
    def complete(*a, **kw):
        stop.set()
        return ToolTurn('', [ToolCall('a', 'write', {})], 1, 1, 2)
    monkeypatch.setattr('app.agent.loop.get_tool', lambda n: executed.append(n))
    events = list(run_agent(SimpleNamespace(complete_with_tools=complete), None, 'x', [{'role':'user','content':'test'}], None, cancelled=stop))
    assert not executed
    assert events[-1][0] == 'error'
    assert '停止' in events[-1][1]['message']


def test_limit_checkpoint_continues_without_repeating_tools(monkeypatch):
    executed = []
    tool = SimpleNamespace(parameters={}, run=lambda s: executed.append(1) or 'saved result')
    monkeypatch.setattr('app.agent.loop.get_tool', lambda name: tool)
    monkeypatch.setattr('app.agent.loop.tool_sources', lambda *a: [])
    client = SimpleNamespace(complete_with_tools=lambda *a, **k: ToolTurn('', [ToolCall('a', 'save', {})], 1, 1, 2))
    first = list(run_agent(client, None, 'x', [{'role':'user','content':'test'}], None, max_iters=1))
    state = first[-1][1]['state']
    assert first[-1][1]['continuable']
    assert state['messages'][-1]['content'] == 'saved result'
    client.complete_with_tools = lambda p, m, messages, *a, **k: ToolTurn(messages[-1]['content'], [], 1, 1, 2)
    second = list(run_agent(client, None, 'x', state['messages'], None, continuation=state))
    assert executed == [1]
    assert second[-1][1]['content'] == 'saved result'


def test_multimodal_compaction_keeps_current_image():
    image = prepare_attachment('image.png', image_bytes()).model_dump()
    current = {'role':'user', 'content':attach_content('看图', [image])}
    history = [{'role':'system','content':'system'}] + [{'role':'user','content':'old '*5000}, {'role':'assistant','content':'answer'}]*4 + [current]
    client = SimpleNamespace(complete=lambda *a, **k: SimpleNamespace(content='summary'))
    result = compact_history(history, client, None, 'x', 12000, keep_recent=1)
    assert result[-1] == current
    assert total_tokens(result) < 12000


def test_step_limit_roundtrip_restores_checkpoint(client, monkeypatch):
    vision, _ = seed()
    cid = client.post('/api/chat/conversations').json()['id']
    monkeypatch.setattr('app.api.chat_api._max_iters', lambda session: 1)
    executed = []
    monkeypatch.setattr('app.agent.loop.get_tool', lambda name: SimpleNamespace(parameters={}, run=lambda s: executed.append(1) or 'result 42'))
    monkeypatch.setattr('app.agent.loop.tool_sources', lambda *a: [])
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', lambda *a, **k: ToolTurn('', [ToolCall('call-1', 'save', {})], 1, 1, 2))
    response = client.post(f'/api/chat/conversations/{cid}/messages/stream', json={'content':'work', 'model_config_id':vision})
    assert 'event: error' in response.text
    assert '"state"' not in response.text
    last = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert last['continuable'] and last['retryable']
    captured = []
    def finish(self, p, m, messages, *a, **k):
        captured.append(messages)
        return ToolTurn('finished', [], 1, 1, 2)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', finish)
    response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content':'work', 'retry_message_id':last['id']})
    assert response.status_code == 200, response.text
    assert captured[0][-1]['content'] == 'result 42'
    assert executed == [1]
    history = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert history[-1]['tools'][0]['name'] == 'save'
    assert history[-1]['tools'][0]['result'] == 'result 42'


@pytest.mark.parametrize('provider_type', ['openai_chat', 'anthropic', 'openai_responses'])
def test_provider_boundary_keeps_image_payload(monkeypatch, provider_type):
    from app.providers.client import ProviderClient
    payloads = []
    def complete(**kwargs):
        payloads.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='image answer', tool_calls=[]))], usage=None)
    def responses(**kwargs):
        payloads.append(kwargs)
        return SimpleNamespace(output=[], output_text='image answer', usage=None)
    monkeypatch.setattr('litellm.completion', complete)
    monkeypatch.setattr('litellm.responses', responses)
    c = ProviderClient(None, None)
    monkeypatch.setattr(c, '_record_usage', lambda *a, **k: None)
    p = Provider(id=1, name='mock', type=provider_type)
    item = prepare_attachment('image.png', image_bytes()).model_dump()
    c.complete_with_tools(p, 'vision-custom', [{'role':'user','content':attach_content('q', [item])}], 'chat')
    key = 'input' if provider_type == 'openai_responses' else 'messages'
    blocks = payloads[0][key][0]['content']
    assert any(b.get('type') == ('input_image' if provider_type == 'openai_responses' else 'image_url') for b in blocks)


def test_context_status_reports_material_payload_and_compaction(monkeypatch):
    current = {'role': 'user', 'content': '本轮问题'}
    history = [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': '很长的旧材料' * 8000}, current]
    client = SimpleNamespace(complete=lambda *a, **k: SimpleNamespace(content='历史摘要'),
                             complete_with_tools=lambda *a, **k: ToolTurn('回答', [], 1, 1, 2))
    events = list(run_agent(client, None, 'x', history, None, context_window=12000))
    status = next(data['context'] for event, data in events if event == 'status' and 'context' in data)
    assert status['before'] == total_tokens(history)
    assert status['after'] < status['before']
    assert status['compacted'] and status['summarized']
    assert status['window'] == 12000


def test_stop_during_compaction_prevents_provider_call(monkeypatch):
    stop = Event()
    called = []
    def compact(messages, *args):
        stop.set()
        return messages
    monkeypatch.setattr('app.agent.loop.compact_history', compact)
    client = SimpleNamespace(complete_with_tools=lambda *a, **k: called.append(True))
    events = list(run_agent(client, None, 'x', [{'role': 'user', 'content': 'q'}], None, cancelled=stop))
    assert not called
    assert events[-1][0] == 'error'

@pytest.mark.parametrize('streaming', [False, True])
def test_review_outage_saves_readable_answer_and_does_not_request_retry(client, monkeypatch, streaming):
    vision, _ = seed()
    cid = client.post('/api/chat/conversations').json()['id']
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', lambda *a, **k: ToolTurn('可阅读的回答。[S1]', [], 1, 1, 2))
    def unavailable(*a, **k):
        raise ValueError('Expecting value: line 1 column 1 (char 0)')
    monkeypatch.setattr('app.agent.loop.review_answer', unavailable)
    monkeypatch.setattr('app.api.chat_api._sources_from_hits', lambda hits: [{'paper_id': 123, 'title': 'test source'}])
    suffix = 'messages/stream' if streaming else 'messages'
    result = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': '解释一下', 'model_config_id': vision, 'review_evidence': True, 'selected_text': 'test source'})
    assert result.status_code == 200
    if streaming:
        assert 'event: done' in result.text and 'event: error' not in result.text
    history = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert history[-2]['delivery_status'] == 'complete'
    assert history[-1]['role'] == 'assistant'
    assert '自动证据复核未完成' in history[-1]['content']
    assert history[-1]['content'].endswith('可阅读的回答。[S1]')

@pytest.mark.parametrize('review', [False, True])
@pytest.mark.parametrize('streaming', [False, True])
def test_extra_review_is_explicit_and_persisted(client, monkeypatch, review, streaming):
    vision, _ = seed()
    cid = client.post('/api/chat/conversations').json()['id']
    calls, prompts = [], []
    def generate(self, provider, model, messages, *a, **k):
        prompts.append(messages)
        return ToolTurn('idea 分析', [], 1, 1, 2)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', generate)
    monkeypatch.setattr('app.api.chat_api._sources_from_hits', lambda hits: [{'paper_id': 123, 'title': 'test source'}])
    def check(*a, **k):
        calls.append(1)
        return a[4], 1, {'status':'complete'}
    monkeypatch.setattr('app.agent.loop.review_answer', check)
    suffix = 'messages/stream' if streaming else 'messages'
    result = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content':'讨论 idea', 'model_config_id':vision, 'review_evidence':review})
    assert result.status_code == 200
    assert len(calls) == int(review)
    assert ('内置科研技能' in prompts[0][0]['content']) == review
    from app.models import Message
    from sqlmodel import select
    with Session(get_engine()) as session:
        user = session.exec(select(Message).where(Message.conversation_id == cid, Message.role == 'user')).first()
        assert json.loads(user.request_json)['review_evidence'] == review
