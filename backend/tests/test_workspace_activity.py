from sqlmodel import Session
from app.db.engine import get_engine
from app.models import ResearchTask, Conversation, Message, LibraryReview, ReviewMap, Paper, PaperDocument
from app.workspaces.context import bind_workspace


def test_activity_directory_distinguishes_same_ids_and_excludes_research_contents(client):
    workspaces=[client.post('/api/workspaces',json={'name':name}).json()['id'] for name in ('A','B')]
    for wid in workspaces:
        with bind_workspace(client.app.state.workspaces.context(wid)),Session(get_engine()) as session:
            session.add(ResearchTask(id='same-id',question='Display title',status='running',paper_ids_json='[]',materials_json='Private research contents'))
            conv=Conversation(title='Conversation title');session.add(conv);session.flush()
            session.add(Message(conversation_id=conv.id,role='user',content='Private user question',delivery_status='pending',model_context='Private model context'))
            session.commit()
    result=client.get('/api/workspaces/activity')
    assert result.status_code==200
    assert 'Private' not in result.text
    rows=result.json()['items']
    assert len(rows)==4 and len({r['key'] for r in rows})==4
    for row in rows:
        assert 'workspace='+row['workspace_id'] in row['url']
        assert row['active']
    client.app.state.workspaces.mark_unavailable(workspaces[0],'Synthetic failure')
    result=client.get('/api/workspaces/activity').json()
    assert all(r['workspace_id']==workspaces[1] for r in result['items'])
    assert result['unavailable'][0]['id']==workspaces[0]


def test_old_running_tasks_and_pending_questions_remain_visible_among_recent_completions(client):
    import json
    from datetime import timedelta
    from app.models.base import utcnow
    with Session(get_engine()) as session:
        session.add(ResearchTask(id='old-running',question='Older ongoing job',status='running',paper_ids_json='[]',updated_at=utcnow()-timedelta(days=10)))
        for i in range(40):
            session.add(ResearchTask(id=str(i),question='Recent finished job',status='ready',paper_ids_json='[]'))
        conv=Conversation(title='Needs an answer');session.add(conv);session.flush()
        session.add(Message(conversation_id=conv.id,role='assistant',content='Private question body',clarification_json=json.dumps({'status':'pending','prompt':'Private prompt'})))
        session.commit()
    response=client.get('/api/workspaces/activity')
    assert 'Private' not in response.text
    rows=response.json()['items']
    assert any(r['key'].endswith(':old-running') and r['active'] for r in rows)
    assert any(r['status']=='awaiting_user' for r in rows)


def test_running_review_maps_surface_even_when_review_is_draft(client):
    with Session(get_engine()) as session:
        for rid, question in (('rev-running', '文献地图要回答的问题'), ('rev-notitle', ''), ('rev-never', '')):
            session.add(LibraryReview(id=rid, question=question, status='draft'))
        session.add(ReviewMap(review_id='rev-running', status='running', stage='正在归类'))
        session.add(ReviewMap(review_id='rev-notitle', status='running'))
        session.add(ReviewMap(review_id='rev-never', status='draft'))
        session.commit()
    rows=client.get('/api/workspaces/activity').json()['items']
    running=[r for r in rows if r['key'].endswith('map:rev-running')]
    assert len(running)==1 and running[0]['kind']=='map' and running[0]['active']
    assert 'map?review=rev-running' in running[0]['url']
    assert running[0]['title']=='文献地图要回答的问题'
    fallback=[r for r in rows if r['key'].endswith('map:rev-notitle')]
    assert len(fallback)==1 and fallback[0]['active'] and fallback[0]['title']=='文献地图 rev-noti'
    assert all(not r['key'].endswith('map:rev-never') for r in rows)


def test_document_conversion_jobs_cover_active_queue_and_recent_errors(client):
    statuses = {1: 'queued', 2: 'running', 3: 'waiting_model', 4: 'error', 5: 'idle'}
    with Session(get_engine()) as session:
        for pid, status in statuses.items():
            session.add(Paper(id=pid, source='pdf', title=f'转换论文 {pid}'))
        session.flush()
        for pid, status in statuses.items():
            session.add(PaperDocument(paper_id=pid, status=status))
        session.commit()
    rows=client.get('/api/workspaces/activity').json()['items']
    imports={r['key']:r for r in rows if r['kind']=='import'}
    assert {key for key, row in imports.items() if row['active']}=={'legacy:import:1', 'legacy:import:2', 'legacy:import:3'}
    assert imports['legacy:import:4']['active'] is False
    assert imports['legacy:import:4']['title']=='转换论文 4' and 'library' in imports['legacy:import:4']['url']
    assert 'legacy:import:5' not in imports
