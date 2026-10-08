"""The selected papers reach the actual agent request and durable source records."""
import copy
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Message, Model, Paper, PaperNote
from test_chat_api import _seed_chat_provider, _turn


def _model_window(window=128000, effort=None):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        model = session.exec(select(Model)).first()
        model.context_window = window
        model.reasoning_effort = effort
        session.add(model)
        session.commit()
        return model.id


def _paper(title, body):
    with Session(get_engine()) as session:
        paper = Paper(source='manual', title=title, full_text=body)
        session.add(paper)
        session.commit()
        return paper.id


def _capturing(captured, reply='A draft based on the supplied papers.'):
    def complete(*args, **kwargs):
        captured.append(copy.deepcopy(args[2]))
        return _turn(reply)
    return complete


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_selected_complete_text_includes_late_evidence_and_durable_pages(client, suffix):
    _model_window()
    body = '<!-- page:1 -->\nBEGIN SELECTED\n' + 'Original methods. ' * 900 + '\n\n<!-- page:5 -->\nTAIL RESULT: treatment = 17; control = 19.'
    pid = _paper('Selected study', body)
    other = _paper('Other study', 'UNSELECTED PRIVATE BODY')
    with Session(get_engine()) as session:
        session.add(PaperNote(paper_id=pid, kind='note', content='Researcher correction: distinguish controls.'))
        session.commit()
    cid = client.post('/api/chat/conversations').json()['id']
    captured = []
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=_capturing(captured)):
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Compare the reported treatment and control.', 'paper_ids': [pid]})
    assert response.status_code == 200
    prompt = '\n'.join(m['content'] for m in captured[0] if isinstance(m['content'], str))
    assert body in prompt and 'UNSELECTED PRIVATE BODY' not in prompt
    assert 'Researcher correction: distinguish controls.' in prompt
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    sources = [s for s in rows[-1]['sources'] if s.get('retrieved_by') == 'selected_full_text']
    assert sources and {s['paper_id'] for s in sources} == {pid}
    assert ''.join(s['excerpt'] for s in sorted(sources, key=lambda s: s['start_char'])) == body
    assert any(5 in s['pages'] and 'TAIL RESULT' in s['excerpt'] for s in sources)
    assert all(not s['excerpt_truncated'] for s in sources)
    with Session(get_engine()) as session:
        user = session.get(Message, rows[0]['id'])
        assert body in user.model_context
        assert session.get(Paper, other).full_text == 'UNSELECTED PRIVATE BODY'


def test_large_paper_is_deferred_whole_and_does_not_displace_another_selected_paper(client):
    _model_window(30000)
    oversized = 'OVERSIZED BEGIN ' + 'large body ' * 18000 + ' OVERSIZED END'
    large = _paper('Long study', oversized)
    small_body = '<!-- page:8 -->\nSMALL COMPLETE BODY with the original controls.'
    small = _paper('Short study', small_body)
    cid = client.post('/api/chat/conversations').json()['id']
    captured = []
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=_capturing(captured)):
        response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Discuss these studies.', 'paper_ids': [large, small]})
    assert response.status_code == 200
    prompt = '\n'.join(m['content'] for m in captured[0] if isinstance(m['content'], str))
    assert 'OVERSIZED BEGIN' not in prompt and 'OVERSIZED END' not in prompt
    assert small_body in prompt and 'get_paper_full_text' in prompt and str(large) in prompt
    sources = response.json()['sources']
    assert {s['paper_id'] for s in sources if s.get('retrieved_by') == 'selected_full_text'} == {small}


def test_configured_reasoning_allowance_is_reserved_before_selected_text(client):
    _model_window(30000)
    body = '<!-- page:3 -->\nBUDGET SENSITIVE ' + '0123456789 ' * 4400
    pid = _paper('Budget study', body)
    captured = []
    first = client.post('/api/chat/conversations').json()['id']
    second = client.post('/api/chat/conversations').json()['id']
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=_capturing(captured)):
        assert client.post(f'/api/chat/conversations/{first}/messages', json={'content': 'Read it.', 'paper_id': pid}).status_code == 200
        with Session(get_engine()) as session:
            model = session.exec(select(Model)).first()
            model.reasoning_effort = 'high'
            session.add(model)
            session.commit()
        assert client.post(f'/api/chat/conversations/{second}/messages', json={'content': 'Read it.', 'paper_id': pid}).status_code == 200
    assert body in captured[0][-1]['content']
    assert body not in captured[1][-1]['content'] and 'BUDGET SENSITIVE' not in captured[1][-1]['content']


def test_retry_keeps_complete_text_and_sources_after_the_library_body_changes(client):
    _model_window()
    original = '<!-- page:7 -->\nIMMUTABLE ORIGINAL with its tested conditions.'
    pid = _paper('Original version', original)
    cid = client.post('/api/chat/conversations').json()['id']
    captured = []
    def fail(*args, **kwargs):
        captured.append(copy.deepcopy(args[2]))
        raise RuntimeError('503 test failure')
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=fail):
        response = client.post(f'/api/chat/conversations/{cid}/messages/stream', json={'content': 'Read the conditions.', 'paper_id': pid})
    assert 'event: error' in response.text
    row = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    with Session(get_engine()) as session:
        paper = session.get(Paper, pid)
        paper.full_text = '<!-- page:99 -->\nNEW BODY MUST NOT REPLACE RETRY'
        session.add(paper)
        session.commit()
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('Recovered')) as model:
        response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': row['content'], 'retry_message_id': row['id']})
    assert response.status_code == 200 and model.call_args.args[2] == captured[0]
    assert original in model.call_args.args[2][-1]['content']
    assert any(s['excerpt'] == original and s['pages'] == [7] for s in response.json()['sources'])


def test_followup_coalesces_unchanged_whole_text_and_keeps_a_later_user_correction(client):
    _model_window()
    body = '<!-- page:2 -->\nUNIQUE FULL EVIDENCE ' + 'the frozen generator matters. ' * 220 + '\n\n<!-- page:9 -->\nFINAL CONDITIONS.'
    pid = _paper('Discussion study', body)
    cid = client.post('/api/chat/conversations').json()['id']
    captured = []
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=_capturing(captured)):
        for question in ['Read the study.', 'My correction: the generator stayed frozen. Continue using that condition.']:
            assert client.post(f'/api/chat/conversations/{cid}/messages', json={'content': question, 'paper_ids': [pid]}).status_code == 200
    prompt = '\n'.join(m['content'] for m in captured[1] if isinstance(m['content'], str))
    assert prompt.count('UNIQUE FULL EVIDENCE') == 1 and prompt.count('FINAL CONDITIONS.') == 1
    assert 'My correction: the generator stayed frozen.' in prompt


def test_highlighted_question_keeps_the_narrow_material_focus(client):
    _model_window()
    pid = _paper('Highlight study', 'WHOLE BODY SHOULD REMAIN TOOL ACCESSIBLE')
    cid = client.post('/api/chat/conversations').json()['id']
    captured = []
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=_capturing(captured)):
        response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Explain this selected sentence.', 'paper_id': pid, 'selected_text': 'SELECTED SENTENCE'})
    assert response.status_code == 200
    assert 'SELECTED SENTENCE' in captured[0][-1]['content']
    assert 'WHOLE BODY SHOULD REMAIN TOOL ACCESSIBLE' not in captured[0][-1]['content']


def test_a_changed_result_keeps_both_whole_text_versions_and_their_snapshot_identity(client):
    _model_window()
    original = '<!-- page:4 -->\nSHARED METHODS ' + 'fixed comparison. ' * 250 + '\n\n<!-- page:10 -->\nOLD RESULT: 17'
    updated = original.replace('OLD RESULT: 17', 'NEW RESULT: 19')
    pid = _paper('Revised study', original)
    cid = client.post('/api/chat/conversations').json()['id']
    captured = []
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=_capturing(captured)):
        assert client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Read it.', 'paper_ids': [pid]}).status_code == 200
        with Session(get_engine()) as session:
            paper = session.get(Paper, pid)
            paper.full_text = updated
            session.add(paper)
            session.commit()
        assert client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Compare the updated result with the prior version.', 'paper_ids': [pid]}).status_code == 200
    prompt = '\n'.join(m['content'] for m in captured[1] if isinstance(m['content'], str))
    assert original in prompt and updated in prompt
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    with Session(get_engine()) as session:
        assert original in session.get(Message, rows[0]['id']).model_context
        assert updated in session.get(Message, rows[2]['id']).model_context


def test_explicit_tool_rejection_uses_already_provided_full_text_without_retrieval(client, monkeypatch):
    _model_window()
    body = '<!-- page:6 -->\nPROVIDED FULL TEXT FOR A PLAIN PROVIDER'
    pid = _paper('Plain provider study', body)
    cid = client.post('/api/chat/conversations').json()['id']
    retrieved, captured = [], []
    def unexpected(*args, **kwargs):
        retrieved.append(True)
        raise AssertionError('Already provided full text must not trigger retrieval')
    def complete(*args, **kwargs):
        if kwargs.get('tools') is not None:
            raise RuntimeError('tools unsupported')
        captured.append(copy.deepcopy(args[2]))
        return _turn('Plain answer')
    monkeypatch.setattr('app.api.chat_api._retrieve_hits', unexpected)
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=complete) as model:
        response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Use the study.', 'paper_ids': [pid]})
    assert response.status_code == 200 and model.call_count == 2
    assert not retrieved
    assert body in captured[0][-1]['content']
    assert '[工具不可用时的论文检索]' not in captured[0][-1]['content']
