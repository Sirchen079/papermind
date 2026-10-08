"""Retrieval belongs to the research step, not every composer submission."""
from unittest.mock import patch
from threading import Event
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from app.db.engine import get_engine
from app.agent.loop import run_agent
from app.models import Paper, PaperChunk
from app.providers.client import ToolCall
from test_chat_api import _seed_chat_provider, _turn
from test_chat_document_revisions import seed

pytestmark = pytest.mark.usefixtures('accept_evidence_review')


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_followup_uses_correction_without_automatic_library_query(client, monkeypatch, suffix):
    _seed_chat_provider()
    cid, _, _ = seed()
    corrected = 'For this question add E and G, eight runs; F is unnecessary.'
    client.post(f'/api/chat/conversations/{cid}/documents/revisions', json={
        'filename': 'comparison.md', 'content': corrected}).raise_for_status()
    queries = []
    monkeypatch.setattr('app.api.chat_api._retrieve_hits', lambda *args: queries.append(args) or [])
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('E and G: eight.')) as model:
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'How many additional runs?'})
    assert response.status_code == 200 and queries == []
    assert any(corrected in m.get('content', '') for m in model.call_args.args[2])
    sources = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]['sources']
    assert all(s.get('retrieved_by') != 'initial_retrieval' for s in sources)


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_agent_can_query_hybrid_index_and_keep_page_sources(client, monkeypatch, suffix):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        paper = Paper(source='manual', title='GSOT noise experiment')
        session.add(paper); session.commit()
        pid = paper.id
        chunk = PaperChunk(paper_id=pid, ordinal=1, text='[第 12 页]\nShared noisy OBS data for both distances.')
        session.add(chunk); session.commit(); session.refresh(chunk); session.expunge(chunk)
    queries = []
    def hybrid(session, query, ids, limit):
        queries.append((query, ids))
        return [chunk]
    monkeypatch.setattr('app.rag.scalable.hybrid', hybrid)
    prefetch = []
    monkeypatch.setattr('app.api.chat_api._retrieve_hits', lambda *args: prefetch.append(args) or [])
    cid = client.post('/api/chat/conversations').json()['id']
    query = 'GSOT OBS noise experiment paired realizations'
    turns = [_turn('', [ToolCall('find', 'search_paper_text', {'query': query, 'paper_ids': [pid]})]),
             _turn('The local excerpt describes shared noisy data.')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=turns):
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Find the experimental evidence'})
    assert response.status_code == 200 and not prefetch
    assert queries == [(query, [pid])]
    last = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert last['tools'][0]['name'] == 'search_paper_text'
    assert len(last['sources']) == 1 and last['sources'][0]['paper_id'] == pid
    assert last['sources'][0]['pages'] == [12]
    assert 'Shared noisy OBS' in last['sources'][0]['excerpt']


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_tool_rejection_retrieves_lazily_and_retry_keeps_snapshot(client, monkeypatch, suffix):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        paper = Paper(source='manual', title='Selected study')
        other = Paper(source='manual', title='Unselected study')
        session.add_all([paper, other]); session.commit()
        pid, other_id = paper.id, other.id
        session.expunge(paper); session.expunge(other)
    selected = PaperChunk(paper_id=pid, ordinal=1, text='Original selected passage.')
    outside = PaperChunk(paper_id=other_id, ordinal=1, text='Outside the requested scope.')
    calls, queries = [], []
    def retrieve(session, query, ids):
        assert calls[-1] == 'tools rejected'
        queries.append((query, ids))
        return [(selected, .9, paper), (outside, .8, other)]
    monkeypatch.setattr('app.api.chat_api._retrieve_hits', retrieve)
    failed = False
    def completion(provider, model_id, messages, request_kind, tools=None, **kwargs):
        nonlocal failed
        if tools:
            calls.append('tools rejected')
            raise RuntimeError('tools are unsupported')
        text = '\n'.join(m.get('content', '') for m in messages)
        assert 'Original selected passage' in text and 'Outside the requested scope' not in text
        if not failed:
            failed = True
            raise TimeoutError('plain request interrupted')
        return _turn('Answered from the persisted passage.')
    cid = client.post('/api/chat/conversations').json()['id']
    body = {'content': 'Explain this experiment', 'paper_ids': [pid]}
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=completion):
        client.post(f'/api/chat/conversations/{cid}/{suffix}', json=body)
        pending = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
        assert pending['retryable']
        selected.text = 'Changed after failed request'
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={
            'content': body['content'], 'retry_message_id': pending['id']})
    assert response.status_code == 200 and queries == [(body['content'], [pid])]
    last = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert len(last['sources']) == 1 and last['sources'][0]['paper_id'] == pid
    assert 'Original selected passage' in last['sources'][0]['excerpt']


@pytest.mark.parametrize('failure', [TimeoutError('timed out'), RuntimeError('invalid API key')])
def test_other_provider_errors_do_not_trigger_retrieval(client, monkeypatch, failure):
    _seed_chat_provider()
    queries = []
    monkeypatch.setattr('app.api.chat_api._retrieve_hits', lambda *args: queries.append(args) or [])
    cid = client.post('/api/chat/conversations').json()['id']
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=failure) as model:
        client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Continue'})
    assert model.call_count == 1 and queries == []
    assert client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]['retryable']


def test_stop_during_tool_rejection_does_not_start_fallback_retrieval():
    stopped = Event()
    queries = []
    def reject(*args, **kwargs):
        stopped.set()
        raise RuntimeError('tools are unsupported')
    events = list(run_agent(SimpleNamespace(complete_with_tools=reject), None, 'test',
        [{'role': 'user', 'content': 'Read this'}], None, cancelled=stopped,
        on_tools_unavailable=lambda: queries.append(True)))
    assert queries == [] and events[-1][0] == 'error'
    assert '已停止' in events[-1][1]['message']
