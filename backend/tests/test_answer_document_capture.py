"""Answer -> local manuscript -> correction -> continued research."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.agent.document_revisions import capture_answer, resume_with_revisions
from app.agent.saved_documents import read_saved_document
from app.agent.web_sources import web_source
from app.config import get_settings
from app.db.engine import get_engine
from app.models import Conversation, Message, Paper
from app.providers.client import ToolCall
from test_chat_api import _seed_chat_provider, _turn


def seed_answer(status='complete', body=None):
    body = body if body is not None else '# FWI 实验建议\n\n在相同初始模型和预算下比较。\n\nB≈C 是待验证假设，不是已有结论。\n'
    with Session(get_engine()) as session:
        conversation = Conversation(title='FWI 振幅与噪声研究')
        paper = Paper(source='manual', title='Objective comparison')
        session.add_all([conversation, paper]); session.commit()
        sources = [{'paper_id': paper.id, 'title': paper.title, 'pages': [14], 'snippet': 'Paper source excerpt'},
            web_source({'url': 'https://example.org/experiment', 'text': 'Web source excerpt',
                        'retrieved_at': '2026-09-26T00:00:00Z'}, 'read_webpage')]
        row = Message(conversation_id=conversation.id, role='assistant', content=body,
            sources_json=json.dumps(sources), model='source-model', delivery_status=status)
        session.add(row); session.commit()
        return conversation.id, row.id, body, sources


@pytest.mark.parametrize('status', ['complete', 'interrupted'])
def test_verbatim_capture_is_local_idempotent_and_preserves_original_and_sources(client, status):
    cid, mid, body, sources = seed_answer(status)
    url = f'/api/chat/conversations/{cid}/messages/{mid}/document'
    with Session(get_engine()) as session:
        original = session.get(Message, mid).model_dump()
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=AssertionError('No model for local save')) as agent, \
         patch('app.providers.client.ProviderClient.complete', side_effect=AssertionError('No model for local save')) as text_model, \
         patch('app.rag.index.retrieve', side_effect=AssertionError('No retrieval for local save')):
        response = client.post(url)
        assert response.status_code == 200
        saved = response.json()
        assert client.post(url).json() == saved
        assert agent.call_count == text_model.call_count == 0
    assert saved['content'] == body and saved['source_delivery_status'] == status
    assert saved['source_model'] == 'source-model' and saved['source_message_id'] == mid
    assert saved['parent_filename'] is None and 'parent_message_id' not in saved
    assert client.get(saved['download_url']).text.replace('\r\n', '\n') == body
    assert (Path(get_settings().data_dir) / 'exports' / saved['filename']).read_text(encoding='utf-8') == body
    history = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert len(history) == 2 and not history[-1]['retryable'] and not history[-1]['tools']
    # The API adds a display description to legacy records; the persisted
    # snapshot below must still remain byte-for-byte faithful to its source.
    assert history[-1]['sources'] == [{**sources[0], 'carried_from_message': mid, 'material_kind': 'unknown'}]
    assert history[-1]['web_sources'] == [{**sources[1], 'carried_from_message': mid}]
    with Session(get_engine()) as session:
        assert session.get(Message, mid).model_dump() == original
        assert json.loads(session.get(Message, saved['message_id']).sources_json) == [{**source, 'carried_from_message': mid} for source in sources]
        doc = json.loads(read_saved_document(session, saved['message_id'], saved['filename']))
        assert doc['material_kind'] == 'assistant_document' and doc['text'] == body
        assert json.loads(read_saved_document(session, saved['message_id'], saved['filename'], part='source', source_index=1))['text'] == 'Web source excerpt'
    item = client.get('/api/chat/saved-documents').json()['items'][0]
    assert item['author'] == 'assistant' and item['capture_message_id'] == mid


def test_capture_edit_and_new_conversation_reuse_correct_version_and_evidence(client, monkeypatch):
    _seed_chat_provider(); monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    cid, mid, body, sources = seed_answer()
    url = f'/api/chat/conversations/{cid}/messages/{mid}/document'
    captured = client.post(url).json()
    corrected = body + '\n人工补充：噪声种子需要配对，幅度扰动单独控制。\n'
    with patch('app.providers.client.ProviderClient.complete_with_tools') as model:
        response = client.post(f'/api/chat/conversations/{cid}/documents/revisions', json={'filename': captured['filename'], 'content': corrected})
    assert response.status_code == 200 and model.call_count == 0
    revision = response.json()
    assert revision['parent_message_id'] == captured['message_id']
    assert revision['parent_filename'] == captured['filename']
    assert client.post(url).json() == captured  # retry never creates another root
    latest = client.get('/api/chat/saved-documents').json()
    assert latest['total'] == 1 and latest['items'][0]['message_id'] == revision['message_id']
    old = client.get(f'/api/chat/saved-documents/{captured["message_id"]}', params={'filename': captured['filename']}).json()
    assert old['content'] == body and old['newer_versions'][0]['message_id'] == revision['message_id']
    assert client.get(captured['download_url']).text.replace('\r\n', '\n') == body
    other = client.post('/api/chat/conversations').json()['id']
    reference = {'message_id': revision['message_id'], 'filename': revision['filename']}
    calls = [_turn('', [ToolCall('read', 'read_saved_document', reference)]),
             _turn('', [ToolCall('source', 'read_saved_document', {**reference, 'part': 'source'})]),
             _turn('Synthetic continuation reads the saved correction and its paper source.')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=calls) as model:
        result = client.post(f'/api/chat/conversations/{other}/messages', json={'content': '根据保存的文档继续设计实验',
            'attachments': [{'name': revision['filename'], 'kind': 'text', 'text': '关联人工修订稿', 'saved_document': reference}]})
    assert result.status_code == 200
    assert any(m['role'] == 'tool' and corrected in json.loads(m['content']).get('text', '') for m in model.call_args.args[2] if m['role'] == 'tool')
    assert any(s.get('pages') == [14] for s in result.json()['sources'])


def test_missing_empty_and_disk_failure_are_retryable_without_losing_answer(client, tmp_path):
    cid, mid, body, _ = seed_answer()
    other = client.post('/api/chat/conversations').json()['id']
    assert client.post(f'/api/chat/conversations/{other}/messages/{mid}/document').status_code == 404
    empty_cid, empty_mid, _, _ = seed_answer(body=' ')
    assert client.post(f'/api/chat/conversations/{empty_cid}/messages/{empty_mid}/document').status_code == 422
    url = f'/api/chat/conversations/{cid}/messages/{mid}/document'
    with patch('app.agent.document_revisions.save_document', side_effect=OSError('disk unavailable')):
        assert client.post(url).status_code == 500
    assert len(client.get(f'/api/chat/conversations/{cid}').json()['messages']) == 1
    assert client.post(url).status_code == 200
    engine = create_engine(f'sqlite:///{tmp_path / "other-workspace.sqlite"}')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            capture_answer(session, cid, mid)
        assert error.value.status_code == 404
    engine.dispose()


def test_saved_answer_does_not_consume_retry_or_become_a_human_correction(client):
    cid, mid, body, _ = seed_answer()
    with Session(get_engine()) as session:
        pending = Message(conversation_id=cid, role='user', content='Continue experiment planning', delivery_status='failed',
            request_json=json.dumps({'content': 'Continue experiment planning'}))
        session.add(pending); session.commit(); pending_id = pending.id
    captured = client.post(f'/api/chat/conversations/{cid}/messages/{mid}/document').json()
    history = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert next(row for row in history if row['id'] == pending_id)['retryable']
    with Session(get_engine()) as session:
        state = resume_with_revisions(session, cid, pending_id, {'messages': []})
        assert len(state['messages']) == 1 and body not in state['messages'][0]['content']
        assert f'message_id={captured["message_id"]}; filename={captured["filename"]}' in state['messages'][0]['content']
        assert 'AI 原回答' in state['messages'][0]['content'] and '修订稿' not in state['messages'][0]['content']


def test_followup_keeps_one_original_answer_and_a_durable_document_reference(client, monkeypatch):
    _seed_chat_provider(); monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    cid, mid, body, _ = seed_answer()
    saved = client.post(f'/api/chat/conversations/{cid}/messages/{mid}/document').json()
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('Synthetic continuation.')) as model:
        response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': '继续讨论'})
    assert response.status_code == 200
    messages = model.call_args.args[2]
    assert sum(body in m.get('content', '') for m in messages) == 1
    assert any(m['role'] == 'assistant' and body in m['content'] for m in messages)
    assert any(f'message_id={saved["message_id"]}; filename={saved["filename"]}' in m.get('content', '') for m in messages)
