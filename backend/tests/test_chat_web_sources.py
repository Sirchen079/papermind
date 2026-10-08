import json
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.agent import research_actions
from app.agent.provenance import merge_sources, public_sources, tool_sources
from app.agent.source_memory import carry_sources, read_chat_sources
from app.agent.saved_documents import read_saved_document
from app.agent.document_revisions import revise_document
from app.db.engine import get_engine
from app.models import Conversation, Message
from app.providers.client import ToolCall, ToolTurn
from test_chat_api import _seed_chat_provider, _turn


URL = 'https://example.org/research/model'
ORIGINAL = 'Published model: compressor-v1. No retraining is required. Device memory is not measured.'


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_actual_web_read_survives_reload_followup_and_saved_document(client, monkeypatch, suffix):
    _seed_chat_provider()
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    monkeypatch.setattr(research_actions, 'fetch_page', lambda url: (url, ORIGINAL.encode(), 'text/plain', 'utf-8'))
    cid = client.post('/api/chat/conversations').json()['id']
    calls = [ToolTurn('', [ToolCall('read', 'read_webpage', {'url': URL})], 1, 1, 2),
             ToolTurn('', [ToolCall('save', 'save_document', {'filename': 'model.md', 'content': 'Published checkpoint.'})], 1, 1, 2),
             _turn('Saved.')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=calls):
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Read the author page and save a note'})
    assert response.status_code == 200
    answer = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    source = answer['web_sources'][0]
    assert source['url'] == URL and source['excerpt'] == ORIGINAL and source['retrieved_at']
    assert answer['sources'] == []  # no synthetic paper ids
    if suffix.endswith('stream'):
        payloads = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert any(row.get('web_sources', [{}])[0].get('excerpt') == ORIGINAL for row in payloads if row.get('web_sources'))
    else:
        assert response.json()['web_sources'] == answer['web_sources']
    detail = client.get(f'/api/chat/saved-documents/{answer["id"]}', params={'filename':'model.md'}).json()
    assert detail['web_sources'] == answer['web_sources'] and detail['sources'] == []
    # The remote site may disappear. Neither manual revision nor a follow-up
    # should refetch it simply to use the passage actually saved earlier.
    monkeypatch.setattr(research_actions, 'fetch_page', lambda url: (_ for _ in ()).throw(RuntimeError('offline')))
    with Session(get_engine()) as session:
        revision = revise_document(session, cid, 'model.md', 'Existing weights are usable; hardware remains unmeasured.')
        record = json.loads(read_saved_document(session, revision['message_id'], revision['filename'], part='source'))
        assert record['text'] == ORIGINAL and record['type'] == 'web'
        assert tool_sources(session, 'read_saved_document', json.dumps(record))[0]['retrieved_at'] == source['retrieved_at']
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('Hardware is still unmeasured.')) as model:
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Use the saved source to continue'})
    assert response.status_code == 200
    assert ORIGINAL in json.dumps(model.call_args.args[2])
    latest = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert latest['web_sources'][0]['snapshot_id'] == source['snapshot_id']


def test_snapshot_pagination_keeps_original_offsets_and_current_conversation_scope(client):
    original = 'Preserved original ' * 1000
    with Session(get_engine()) as session:
        source = tool_sources(session, 'read_webpage', json.dumps({'url':URL, 'text':original, 'start_char':5000}))[0]
        conv = Conversation(title='Source'); other = Conversation(title='Other')
        session.add_all([conv, other]); session.commit()
        old = Message(conversation_id=conv.id, role='assistant', content='Read', sources_json=json.dumps([source]))
        session.add(old); session.commit()
        current = Message(conversation_id=conv.id, role='user', content='Continue')
        session.add(current); session.commit()
        block, carried = carry_sources(session, conv.id, current.id, None, 600)
        assert not carried and 'source_index' in block and original not in block
        session.info['chat_conversation_id'] = conv.id
        first = json.loads(read_chat_sources(session, old.id, 0, max_chars=700))
        second = json.loads(read_chat_sources(session, old.id, 0, start_char=first['next_start_char'], max_chars=700))
        assert first['text'] + second['text'] == original[:1400]
        restored = tool_sources(session, 'read_chat_sources', json.dumps(second))[0]
        assert restored['start_char'] == 5700 and restored['end_char'] == 6400
        assert restored['snapshot_id'] == source['snapshot_id']
        session.info['chat_conversation_id'] = other.id
        assert 'error' in json.loads(read_chat_sources(session, old.id, 0))


def test_search_link_is_not_a_read_snapshot_and_different_versions_remain_distinct(client):
    with Session(get_engine()) as session:
        assert tool_sources(session, 'search_web', json.dumps({'results':[{'url':URL, 'title':'A result'}]})) == []
        assert tool_sources(session, 'read_webpage', json.dumps({'url':URL, 'text':''})) == []
        a = tool_sources(session, 'read_webpage', json.dumps({'url':URL, 'text':'Old published text.'}))[0]
        b = tool_sources(session, 'read_webpage', json.dumps({'url':URL, 'text':'Changed published text.'}))[0]
        rows = [a]; merge_sources(rows, [a, b])
        assert len(rows) == 2 and public_sources(rows)['sources'] == []
        assert len(public_sources(rows)['web_sources']) == 2


def test_web_excerpt_is_available_to_optional_evidence_review(client, monkeypatch):
    _seed_chat_provider(); monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    monkeypatch.setattr(research_actions, 'fetch_page', lambda url: (url, ORIGINAL.encode(), 'text/plain', 'utf-8'))
    cid = client.post('/api/chat/conversations').json()['id']
    def review(client, provider, model, question, draft, evidence, context_window=None):
        assert ORIGINAL in '\n'.join(item['text'] for item in evidence)
        return draft, 0, {'edits':[]}
    calls = [ToolTurn('', [ToolCall('read', 'read_webpage', {'url':URL})], 1,1,2), _turn('A draft.')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=calls), patch('app.agent.loop.review_answer', side_effect=review):
        assert client.post(f'/api/chat/conversations/{cid}/messages', json={'content':'Read this source','review_evidence':True}).status_code == 200
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('Short draft.')), patch('app.agent.loop.review_answer', side_effect=review):
        assert client.post(f'/api/chat/conversations/{cid}/messages', json={'content':'Continue','review_evidence':True}).status_code == 200
