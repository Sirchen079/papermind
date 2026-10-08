import json

from sqlmodel import Session

from app.agent.document_revisions import revise_document, save_revision
from app.agent.saved_documents import get_document, list_documents, read_saved_document
from app.db.engine import get_engine
from app.models import Conversation, Message
from test_chat_document_revisions import seed


def test_reading_old_version_exposes_latest_descendant_without_replacing_it(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        first = revise_document(session, cid, 'comparison.md', 'First correction.')
        last = revise_document(session, cid, first['filename'], 'Final correction.')
        old = json.loads(read_saved_document(session, mid, 'comparison.md'))
        assert old['text'] == 'Original incorrect draft.'
        assert [v['message_id'] for v in old['newer_versions']] == [last['message_id']]
        assert old['newer_versions'][0]['filename'] == last['filename']
        assert old['newer_versions'][0]['created_at'].endswith('+00:00')
        assert old['created_at'].endswith('+00:00')
        assert 'content' not in old['newer_versions'][0] and 'sources' not in old['newer_versions'][0]
        assert get_document(session, last['message_id'], last['filename'])['newer_versions'] == []
        source = json.loads(read_saved_document(session, mid, 'comparison.md', part='source'))
        assert source['text'] == 'source excerpt' and source['saved_message_id'] == mid


def test_cross_conversation_branches_stay_separate_and_do_not_match_unrelated_names(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        other = Conversation(title='Alternative scope'); session.add(other); session.commit()
        origin = session.get(Message, mid)
        one = revise_document(session, cid, 'comparison.md', 'Correction for scope A.')
        two = save_revision(session, other, origin, 'comparison.md', 'Alternative scope B.')
        assert {v['message_id'] for v in get_document(session, mid, 'comparison.md')['newer_versions']} == {one['message_id'], two['message_id']}
        assert get_document(session, one['message_id'], one['filename'])['newer_versions'] == []
        assert get_document(session, two['message_id'], two['filename'])['newer_versions'] == []
        later = revise_document(session, other.id, two['filename'], 'Further correction for scope B.')
        assert {v['message_id'] for v in get_document(session, mid, 'comparison.md')['newer_versions']} == {one['message_id'], later['message_id']}
        other_id = other.id
    # Removing that conversation must not leave unusable version links.
    client.delete(f'/api/chat/conversations/{other_id}')
    response = client.get(f'/api/chat/saved-documents/{mid}', params={'filename': 'comparison.md'})
    assert [v['message_id'] for v in response.json()['newer_versions']] == [one['message_id']]


def test_restoring_original_content_keeps_restored_version_discoverable(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        first = revise_document(session, cid, 'comparison.md', 'Temporary correction.')
        restored = revise_document(session, cid, first['filename'], 'Original incorrect draft.')
        assert restored['filename'] == 'comparison.md'  # same file, distinct revision record
        records = list_documents(session)['items']
        assert len(records) == 1 and records[0]['message_id'] == restored['message_id']
        assert [v['message_id'] for v in get_document(session, mid, 'comparison.md')['newer_versions']] == [restored['message_id']]
        assert get_document(session, restored['message_id'], restored['filename'])['newer_versions'] == []


def test_legacy_parent_filename_remains_supported(client):
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        revision = revise_document(session, cid, 'comparison.md', 'Legacy correction.')
        row = session.get(Message, revision['message_id'])
        data = json.loads(row.request_json); data['document_revision'].pop('parent_message_id', None)
        row.request_json = json.dumps(data); session.add(row); session.commit()
        assert get_document(session, mid, 'comparison.md')['newer_versions'][0]['message_id'] == row.id
