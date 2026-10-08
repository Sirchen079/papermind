import json
from unittest.mock import patch
import pytest

from sqlmodel import Session, SQLModel, create_engine

from app.agent.saved_documents import list_documents, get_document, read_saved_document
from app.agent.document_revisions import revise_document
from app.agent.provenance import tool_sources
from app.db.engine import get_engine
from app.models import Conversation, Message, Paper
from app.providers.client import ToolCall, ToolTurn
from test_chat_document_revisions import seed
from test_chat_api import _seed_chat_provider, _turn


def test_generation_request_follows_exact_revision_and_capture_ancestry(client):
    from app.agent.document_revisions import capture_answer, save_revision
    with Session(get_engine()) as session:
        origin = Conversation(title='Original research')
        other = Conversation(title='Different research')
        session.add_all([origin, other]); session.commit()
        request = Message(conversation_id=origin.id, role='user', content='Evidence budget is 4K; save a comparison.')
        session.add(request); session.commit()
        unrelated = Message(conversation_id=other.id, role='user', content='Use an 8K budget.')
        session.add(unrelated); session.commit()
        answer = Message(conversation_id=origin.id, role='assistant', content='Comparison with uncertain budget.')
        session.add(answer); session.commit()
        later = Message(conversation_id=origin.id, role='user', content='Now work on another project.')
        session.add(later); session.commit()
        captured = capture_answer(session, origin.id, answer.id)
        capture_row = session.get(Message, captured['message_id'])
        revision = save_revision(session, other, capture_row, captured['filename'], 'Manually changed to 6K.')
        second = save_revision(session, other, session.get(Message, revision['message_id']), revision['filename'], 'New version.')
        for record in (captured, revision, second):
            doc = get_document(session, record['message_id'], record['filename'])
            assert doc['generation_request']['message_id'] == request.id
            assert doc['generation_request']['content'] == request.content
            assert doc['generation_request']['conversation_id'] == origin.id
            assert '当前用户要求与后续修订优先' in doc['generation_request']['note']
        result = json.loads(read_saved_document(session, second['message_id'], second['filename']))
        assert result['generation_request']['content'] == request.content
        assert result['text'] == 'New version.'
        assert all('generation_request' not in row for row in list_documents(session)['items'])
    response = client.get(f'/api/chat/saved-documents/{second["message_id"]}', params={'filename': second['filename']})
    assert response.json()['generation_request']['content'] == 'Evidence budget is 4K; save a comparison.'


def test_generation_request_does_not_invent_missing_legacy_or_cyclic_ancestry(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        assert get_document(session, mid, 'comparison.md')['generation_request'] is None
        revision = revise_document(session, cid, 'comparison.md', 'Manual content.')
        row = session.get(Message, revision['message_id'])
        metadata = json.loads(row.request_json)
        for parent in (None, row.id, row.id + 1):
            metadata['document_revision']['parent_message_id'] = parent
            row.request_json = json.dumps(metadata); session.add(row); session.commit()
            doc = get_document(session, row.id, revision['filename'])
            assert doc['generation_request'] is None
            assert doc['content'] == 'Manual content.'


def test_generation_request_skips_saved_document_notices(client):
    with Session(get_engine()) as session:
        conversation = Conversation(title='Research')
        session.add(conversation); session.commit()
        request = Message(conversation_id=conversation.id, role='user', content='Compare these methods.')
        session.add(request); session.commit()
        notice = Message(conversation_id=conversation.id, role='user', content='Saved manually.',
                         request_json=json.dumps({'document_revision': {'filename': 'old.md'}}))
        session.add(notice); session.commit()
        answer = Message(conversation_id=conversation.id, role='assistant', content='Saved.',
            agent_state_json=json.dumps({'tools': [{'name': 'save_document', 'ok': True,
                'args': {'content': 'Draft'}, 'result': json.dumps({'ok': True, 'filename': 'draft.md'})}]}))
        session.add(answer); session.commit()
        result = json.loads(read_saved_document(session, answer.id, 'draft.md'))
        assert result['generation_request']['message_id'] == request.id
        assert result['generation_request']['content'] == request.content


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_document_reference_routes_to_agent_sources_and_survives_retry(client, monkeypatch, suffix):
    _seed_chat_provider()
    _, mid, _ = seed()
    cid = client.post('/api/chat/conversations').json()['id']
    def unwanted_prefetch(*args, **kwargs):
        raise AssertionError('Generic editing instruction must not be used as the library query')
    monkeypatch.setattr('app.api.chat_api._retrieve_hits', unwanted_prefetch)
    searches = []
    monkeypatch.setattr('app.rag.scalable.hybrid', lambda session, query, *args, **kw: searches.append(query) or [])
    reference = {'message_id': mid, 'filename': 'comparison.md'}
    attachment = {'name': 'comparison.md', 'kind': 'text', 'text': 'Check this paragraph from my saved comparison.',
                  'saved_document': reference}
    calls = [TimeoutError('synthetic timeout'),
             _turn('', [ToolCall('read', 'read_saved_document', {**reference, 'part': 'source'})]),
             _turn('', [ToolCall('search', 'search_paper_text', {'query': 'query reformulation training samples'})]),
             _turn('A local revision based on the saved original excerpt.')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=calls) as model:
        client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Check this passage', 'attachments': [attachment]})
        first = client.get(f'/api/chat/conversations/{cid}').json()['messages'][0]
        assert first['retryable'] and first['attachments'][0]['saved_document'] == reference
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': first['content'], 'retry_message_id': first['id']})
    assert response.status_code == 200
    history = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert len(history) == 2 and history[-1]['role'] == 'assistant'
    assert history[0]['attachments'][0]['saved_document'] == reference
    assert searches == ['query reformulation training samples']
    assert any(s.get('pages') == [14] for s in history[-1]['sources'])
    assert any(m['role'] == 'tool' and 'source excerpt' in m['content'] for m in model.call_args.args[2])
    assert any(m['role'] == 'user' and f'message_id={mid}; filename=comparison.md' in str(m['content']) for m in model.call_args.args[2])


@pytest.mark.parametrize('attachment_text', [None, 'Uploaded experiment notes', '关联已保存文档：legacy-note.md'])
def test_unlinked_questions_and_legacy_uploads_leave_retrieval_to_agent(client, monkeypatch, attachment_text):
    _seed_chat_provider()
    queries = []
    monkeypatch.setattr('app.api.chat_api._retrieve_hits', lambda session, query, *args: queries.append(query) or [])
    cid = client.post('/api/chat/conversations').json()['id']
    body = {'content': 'Find work about retrieval control'}
    if attachment_text:
        body['attachments'] = [{'name': 'notes.md', 'kind': 'text', 'text': attachment_text}]
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('Found related work.')):
        assert client.post(f'/api/chat/conversations/{cid}/messages', json=body).status_code == 200
    assert queries == []


def test_find_latest_manual_revision_and_open_older_versions(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        revision = revise_document(session, cid, 'comparison.md', 'Corrected unique comparison about retrieval.')
    latest = client.get('/api/chat/saved-documents').json()
    assert latest['total'] == 1 and latest['items'][0]['author'] == 'user'
    assert latest['items'][0]['message_id'] == revision['message_id']
    assert client.get('/api/chat/saved-documents?q=unique').json()['total'] == 1
    assert client.get('/api/chat/saved-documents?q=absent').json()['total'] == 0
    history = client.get('/api/chat/saved-documents?include_previous_versions=true&limit=1').json()
    assert history['total'] == 2 and history['next_offset'] == 1
    older = client.get('/api/chat/saved-documents?include_previous_versions=true&offset=1').json()['items'][0]
    assert older['filename'] == 'comparison.md' and older['superseded']
    detail = client.get(f'/api/chat/saved-documents/{revision["message_id"]}', params={'filename': revision['filename']})
    assert detail.status_code == 200 and detail.json()['content'].startswith('Corrected unique')
    assert client.get(f'/api/chat/saved-documents/{mid}', params={'filename': revision['filename']}).status_code == 404


def test_document_snapshot_is_not_original_evidence_and_sources_are_read_separately(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        session.info['chat_conversation_id'] = 999  # another conversation in this workspace
        doc = read_saved_document(session, mid, 'comparison.md')
        assert json.loads(doc)['material_kind'] == 'assistant_document'
        assert tool_sources(session, 'read_saved_document', doc) == []
        source = read_saved_document(session, mid, 'comparison.md', part='source')
        sources = tool_sources(session, 'read_saved_document', source)
        assert sources[0]['pages'] == [14] and sources[0]['carried_from_message'] == mid
        paper = session.get(Paper, sources[0]['paper_id']); paper.is_deleted = True
        session.add(paper); session.commit()
        assert 'error' in json.loads(read_saved_document(session, mid, 'comparison.md', part='source'))
        assert json.loads(read_saved_document(session, mid, 'comparison.md'))['text']  # user work remains readable


def test_workspace_isolation_and_progressive_reading(client, tmp_path):
    cid, mid, _ = seed()
    content = 'Long manually corrected content. ' * 1200
    with Session(get_engine()) as session:
        revision = revise_document(session, cid, 'comparison.md', content)
        chunks = []; start = 0
        while True:
            part = json.loads(read_saved_document(session, revision['message_id'], revision['filename'], start_char=start, max_chars=777))
            chunks.append(part['text']); start = part['next_start_char']
            if start is None: break
        assert ''.join(chunks) == content
    engine = create_engine(f'sqlite:///{tmp_path / "other.sqlite"}')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as other:
        assert list_documents(other)['items'] == []
        assert 'error' in json.loads(read_saved_document(other, mid, 'comparison.md'))
    engine.dispose()


def test_failed_saves_are_not_discoverable_and_deleted_conversations_disappear(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        row = session.get(Message, mid)
        state = json.loads(row.agent_state_json); state['tools'][0]['ok'] = False
        row.agent_state_json = json.dumps(state); session.add(row); session.commit()
        assert list_documents(session)['items'] == []
        state['tools'][0]['ok'] = True
        row.agent_state_json = json.dumps(state); session.add(row); session.commit()
        assert list_documents(session)['total'] == 1
    assert client.delete(f'/api/chat/conversations/{cid}').status_code == 204
    assert client.get('/api/chat/saved-documents').json()['total'] == 0


def test_agent_can_reuse_saved_manual_work_from_a_new_conversation(client, monkeypatch):
    _seed_chat_provider(); monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    cid, mid, _ = seed()
    correction = 'RJ: sample then filter and downsample. QR: distinct annotation dataset.'
    with Session(get_engine()) as session:
        revision = revise_document(session, cid, 'comparison.md', correction)
    new_cid = client.post('/api/chat/conversations').json()['id']
    calls = [ToolTurn('', [ToolCall('find', 'search_saved_documents', {'query': 'comparison'})], 1, 1, 2),
        ToolTurn('', [ToolCall('read', 'read_saved_document', {'message_id': revision['message_id'], 'filename': revision['filename']})], 1, 1, 2), _turn('Continue from your manual work.')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=calls) as model:
        result = client.post(f'/api/chat/conversations/{new_cid}/messages', json={'content': 'Continue from my saved comparison'})
    assert result.status_code == 200
    messages = model.call_args.args[2]
    assert any(m['role'] == 'tool' and correction in m['content'] and 'user_revision' in m['content'] for m in messages)
    assert not result.json()['sources']  # document writing alone is not paper evidence


def test_saved_audit_metadata_survives_discovery_and_reread(client):
    from app.agent.document_revisions import save_revision
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        saved = save_revision(session, session.get(Conversation, cid), session.get(Message, mid),
            'comparison.md', 'Draft for discussion, not adopted.', note='Audit saved.',
            extra={'audit_author': 'Codex', 'adoption_status': 'not_user_adopted'})
        item = list_documents(session)['items'][0]
        doc = json.loads(read_saved_document(session, saved['message_id'], saved['filename']))
        for result in (item, doc):
            assert result['filename'] == saved['filename'] and result['message_id'] == saved['message_id']
            assert result['audit_author'] == 'Codex' and result['adoption_status'] == 'not_user_adopted'
        assert doc['material_kind'] == 'research_document'
        assert doc['text'] == 'Draft for discussion, not adopted.'
        assert {r['message_id'] for r in list_documents(session)['items']} == {mid, saved['message_id']}
        descendant = get_document(session, mid, 'comparison.md')['newer_versions'][0]
        assert descendant['audit_author'] == 'Codex'
        assert descendant['adoption_status'] == 'not_user_adopted'


def test_unadopted_draft_keeps_prior_work_until_user_saves_a_descendant(client):
    from app.agent.document_revisions import save_revision
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        manual = revise_document(session, cid, 'comparison.md', 'User established conditions.')
        author = session.get(Conversation, cid)
        audit = save_revision(session, author, session.get(Message, manual['message_id']),
            manual['filename'], 'Proposed change, not adopted.', note='Saved for discussion.',
            extra={'audit_author':'Codex','adoption_status':'not_user_adopted'})
        assert {r['message_id'] for r in list_documents(session)['items']} == {manual['message_id'], audit['message_id']}
        versions = get_document(session, mid, 'comparison.md')['newer_versions']
        assert {r['message_id'] for r in versions} == {manual['message_id'], audit['message_id']}
        accepted = revise_document(session, cid, audit['filename'], 'User chose an edited alternative.')
        assert [r['message_id'] for r in list_documents(session)['items']] == [accepted['message_id']]
        versions = get_document(session, mid, 'comparison.md')['newer_versions']
        assert [r['message_id'] for r in versions] == [accepted['message_id']]
        assert 'adoption_status' not in versions[0]  # No inherited unadopted flag after user action.
        assert get_document(session, manual['message_id'], manual['filename'])['content'] == 'User established conditions.'
        same_text_audit = save_revision(session, author, session.get(Message, accepted['message_id']),
            accepted['filename'], 'User chose an edited alternative.', note='Independent draft record.',
            extra={'audit_author':'Codex','adoption_status':'not_user_adopted'})
        assert same_text_audit['filename'] == accepted['filename']
        assert {r['message_id'] for r in list_documents(session)['items']} == {accepted['message_id'], same_text_audit['message_id']}
