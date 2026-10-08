"""Research-document navigation follows real reads, not inferred citations."""
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Conversation, Message
from app.agent.document_revisions import revise_document, capture_answer
from app.agent.saved_documents import get_document, read_saved_document
from app.agent.presentation import public_tool_result
from app.providers.client import ToolCall
from test_chat_api import _seed_chat_provider, _turn
from test_chat_document_revisions import seed


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_real_tool_receipts_support_cross_conversation_document_navigation(client, monkeypatch, suffix):
    _seed_chat_provider()
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **kw: [])
    old_cid, old_mid, _ = seed()
    with Session(get_engine()) as session:
        revision = revise_document(session, old_cid, 'comparison.md', 'A long saved research record. ' * 900)
    ref = {key: revision[key] for key in ('message_id', 'filename')}
    cid = client.post('/api/chat/conversations').json()['id']
    calls = [
        _turn('', [ToolCall('read', 'read_saved_document', ref)]),
        _turn('', [ToolCall('save', 'save_document', {'filename': 'derived.md', 'content': 'New table from the existing record.'})]),
        _turn('Saved the table.'),
    ]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=calls) as model:
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': '整理旧稿',
            'attachments': [{'name': ref['filename'], 'kind': 'text', 'text': 'Use the linked record.', 'saved_document': ref}]})
    assert response.status_code == 200
    history = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    mid = history[-1]['id']
    doc = client.get(f'/api/chat/saved-documents/{mid}', params={'filename': 'derived.md'}).json()
    entry, = doc['input_documents']
    assert entry['message_id'] == ref['message_id'] and entry['filename'] == ref['filename']
    assert entry['relations'] == ['attached', 'read'] and entry['available']
    assert entry['reads'] == [{'part': 'document', 'start_char': 0, 'loaded_chars': 12000}]
    assert doc['sources'] == []  # A research record is not newly read primary evidence.
    receipt = json.loads(history[-1]['tools'][0]['result'])
    assert receipt['loaded_chars'] == 12000 and len(receipt['text_preview']) == 280
    assert any(m['role'] == 'tool' and len(m['content']) > 12000 for m in model.call_args.args[2])
    with Session(get_engine()) as session:
        edited = revise_document(session, cid, 'derived.md', 'Locally corrected table.')
        edited_doc = get_document(session, edited['message_id'], edited['filename'])
        assert edited_doc['input_documents'][0]['relations'] == ['revision_parent']
        assert edited_doc['input_documents'][1] == entry
        captured = capture_answer(session, cid, mid)
        assert get_document(session, captured['message_id'], captured['filename'])['input_documents'] == [entry]
        # The agent can follow the same input pointer when continuing the revised artifact.
        reread = json.loads(read_saved_document(session, edited['message_id'], edited['filename']))
        assert reread['input_documents'][1] == entry


def test_reads_are_scoped_to_save_order_and_do_not_expand_recursively(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        alt = revise_document(session, cid, 'comparison.md', 'Alternative record.')
        old_ref = {'message_id': mid, 'filename': 'comparison.md'}
        alt_ref = {'message_id': alt['message_id'], 'filename': alt['filename']}
        source_result = read_saved_document(session, **old_ref, part='source')
        source_receipt = public_tool_result('read_saved_document', source_result)
        tools = [
            {'name': 'read_saved_document', 'ok': True, 'args': {**old_ref, 'part': 'source'}, 'result': source_receipt},
            {'name': 'save_document', 'ok': True, 'args': {'content': 'First'}, 'result': json.dumps({'ok': True, 'filename': 'first.md'})},
            {'name': 'read_saved_document', 'ok': True, 'args': alt_ref, 'result': public_tool_result('read_saved_document', read_saved_document(session, **alt_ref))},
            {'name': 'save_document', 'ok': True, 'args': {'content': 'Second'}, 'result': json.dumps({'ok': True, 'filename': 'second.md'})},
            {'name': 'read_saved_document', 'ok': True, 'args': {'message_id': mid, 'filename': 'absent.md'}, 'result': '{"error":"missing"}'},
        ]
        message = Message(conversation_id=cid, role='assistant', content='Two files', agent_state_json=json.dumps({'tools': tools}))
        session.add(message); session.commit()
        first = get_document(session, message.id, 'first.md')['input_documents']
        second = get_document(session, message.id, 'second.md')['input_documents']
        assert len(first) == 1 and first[0]['reads'][0]['part'] == 'source'
        assert len(second) == 2 and second[1]['message_id'] == alt['message_id']
        assert 'input_documents' not in second[1]  # follow links on demand


def test_legacy_truncated_receipt_and_missing_target_remain_honest(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        tools = [
            {'name': 'read_saved_document', 'ok': True, 'args': {'message_id': mid, 'filename': 'comparison.md'}, 'result': '{"message_id":1,"content":"truncated'},
            {'name': 'read_saved_document', 'ok': False, 'args': {'message_id': mid, 'filename': 'bad.md'}, 'result': 'failed'},
            {'name': 'save_document', 'ok': True, 'args': {'content': 'Legacy draft'}, 'result': '{"ok":true,"filename":"legacy.md"}'},
        ]
        other = Conversation(title='New work'); session.add(other); session.commit()
        message = Message(conversation_id=other.id, role='assistant', content='Legacy draft saved.', agent_state_json=json.dumps({'tools': tools}))
        session.add(message); session.commit()
        doc = get_document(session, message.id, 'legacy.md')
        entry, = doc['input_documents']
        assert entry['relations'] == ['read_unconfirmed'] and entry['reads'] == [] and entry['available']
        session.delete(session.get(Message, mid)); session.commit()
        missing, = get_document(session, message.id, 'legacy.md')['input_documents']
        assert not missing['available'] and missing['filename'] == 'comparison.md'
        assert get_document(session, message.id, 'legacy.md')['content'] == 'Legacy draft'
