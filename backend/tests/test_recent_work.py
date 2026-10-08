from datetime import timedelta
import json

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Conversation, Message, ResearchTask, WikiPage, WikiUpdate
from app.models.base import utcnow
from app.models.review import LibraryReview
from app.workspaces.context import bind_workspace


def test_recent_work_stays_in_selected_project_and_contains_no_transcripts(client):
    ids = [client.post('/api/workspaces', json={'name': name}).json()['id'] for name in ('A', 'B')]
    for wid in ids:
        with bind_workspace(client.app.state.workspaces.context(wid)), Session(get_engine()) as session:
            session.add(LibraryReview(id='same-id', question=wid, status='ready', content='PRIVATE manuscript'))
            conv = Conversation(title='Conversation in ' + wid)
            session.add(conv); session.flush()
            session.add(Message(conversation_id=conv.id, role='user', content='PRIVATE question',
                                model_context='PRIVATE source', request_json='{"secret":"PRIVATE"}'))
            session.commit()
    response = client.get(f'/api/w/{ids[0]}/research/recent-work')
    assert response.status_code == 200
    assert 'PRIVATE' not in response.text and ids[1] not in response.text
    rows = response.json()['items']
    assert len(rows) == 2
    assert next(r for r in rows if r['kind'] == 'review')['route'] == 'research?mode=review&review=same-id'
    assert client.get('/api/research/recent-work').json() == {'items': []}


def test_long_conversation_does_not_crowd_out_other_work_and_revision_is_recent(client):
    now = utcnow()
    with Session(get_engine()) as session:
        long = Conversation(title='Long conversation', updated_at=now - timedelta(days=1))
        revised = Conversation(title='Manually revised draft', updated_at=now)
        session.add(long); session.add(revised); session.flush()
        session.add(Message(conversation_id=revised.id, role='user', content='PRIVATE adopted version',
                            created_at=now, request_json=json.dumps({'document_revision': {'filename': 'draft-v2.md'}})))
        for _ in range(50):
            session.add(Message(conversation_id=long.id, role='user', content='PRIVATE turn', created_at=now - timedelta(days=1)))
        session.add(Conversation(title='Empty, never used'))
        session.commit()
    rows = client.get('/api/research/recent-work').json()['items']
    assert [r['title'] for r in rows] == ['Manually revised draft', 'Long conversation']
    assert len({r['route'] for r in rows}) == 2


def test_latest_turn_controls_waiting_failed_and_running_status(client):
    with Session(get_engine()) as session:
        for title, status in [('Awaiting answer', 'awaiting_user'), ('Later failure', 'failed'), ('Later run', 'pending')]:
            conv = Conversation(title=title); session.add(conv); session.flush()
            session.add(Message(conversation_id=conv.id, role='assistant', content='PRIVATE',
                                clarification_json='{"status":"pending"}'))
            session.flush()
            if status != 'awaiting_user':
                session.add(Message(conversation_id=conv.id, role='user', content='PRIVATE', delivery_status=status))
                session.flush()
        session.commit()
    rows = client.get('/api/research/recent-work').json()['items']
    assert {r['title']: r['status'] for r in rows} == {'Awaiting answer': 'awaiting_user', 'Later failure': 'failed', 'Later run': 'pending'}
    assert rows[-1]['title'] == 'Later failure'


def test_ongoing_review_remains_visible_and_drafts_are_resumable(client):
    with Session(get_engine()) as session:
        session.add(LibraryReview(id='ongoing', question='Older run', status='running', updated_at=utcnow() - timedelta(days=10)))
        for i in range(30):
            session.add(ResearchTask(id=str(i), question='Recent draft', status='draft', paper_ids_json='[]'))
        session.commit()
    rows = client.get('/api/research/recent-work?limit=3').json()['items']
    assert len(rows) == 3 and rows[0]['key'] == 'review:ongoing'
    assert rows[0]['active'] and rows[1]['status'] == 'draft'
    assert client.get('/api/research/recent-work?limit=0').status_code == 422
    assert client.get('/api/research/recent-work?limit=1000').status_code == 422


def test_manual_wiki_and_latest_update_share_one_entry_archives_excluded(client):
    with Session(get_engine()) as session:
        session.add(WikiPage(id='manual', title='Manual notes'))
        session.add(WikiPage(id='generated', title='Generated notes'))
        session.add(WikiPage(id='archived', title='Archived notes', archived=True))
        session.flush()
        for i in range(35):
            session.add(WikiUpdate(id=str(i), page_id='generated', base_version=0, request_hash='x',
                                   inputs_json='PRIVATE', status='done', updated_at=utcnow() + timedelta(seconds=i)))
        session.commit()
    rows = client.get('/api/research/recent-work').json()['items']
    assert {r['key'] for r in rows} == {'wiki:manual', 'wiki:generated'}
    assert next(r for r in rows if r['key'] == 'wiki:manual')['status'] == 'saved'
    assert next(r for r in rows if r['key'] == 'wiki:generated')['route'] == 'wiki?page=generated'


def test_global_activity_includes_review_completion_without_changing_turn_keys(client):
    with Session(get_engine()) as session:
        review = LibraryReview(id='review', question='Review work', status='running', content='PRIVATE manuscript')
        session.add(review)
        conv = Conversation(title='Conversation'); session.add(conv); session.flush()
        user = Message(conversation_id=conv.id, role='user', content='PRIVATE turn')
        session.add(user); session.commit(); session.refresh(user)
        mid = user.id
    before = client.get('/api/workspaces/activity').json()['items']
    assert {r['key'] for r in before} == {'legacy:review:review', f'legacy:chat:{mid}'}
    with Session(get_engine()) as session:
        row = session.get(LibraryReview, 'review'); row.status = 'ready'; session.add(row); session.commit()
    response = client.get('/api/workspaces/activity')
    assert 'PRIVATE' not in response.text
    after = next(r for r in response.json()['items'] if r['kind'] == 'review')
    previous = next(r for r in before if r['kind'] == 'review')
    assert previous['active'] and not after['active'] and previous['stamp'] != after['stamp']
    assert after['url'] == '?workspace=legacy#research?mode=review&review=review'
