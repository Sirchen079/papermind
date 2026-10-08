import json
from uuid import uuid4
from sqlmodel import Session,select
from app.models import PaperNoteRevision
from app.db.engine import get_engine
from app.agent.paper_notes import read_paper_notes
from app.agent.provenance import tool_sources


def seed(client):
    paper=client.post('/api/papers/manual',json={'title':'FWI source conditions'}).json()['id']
    prefix=f'/api/papers/{paper}/reading/notes'
    note=client.post(prefix,json={'content':'原始判断😀\n\n[Paper: PDF p. 3]','kind':'critique','tags':['条件']}).json()
    return paper,prefix,note


def test_correction_restore_noop_conflict_and_export(client):
    pid,prefix,note=seed(client);path=f"{prefix}/{note['id']}"
    changed=client.patch(path,json={'content':'修订：受控噪声结果不代表现场排名。','expected_version':1}).json()
    assert changed['version']==2
    historic=client.get(path+'/revisions/1').json();assert historic['content']==note['content']
    assert historic['tags']==['条件'] and historic['kind']=='critique'
    assert client.patch(path,json={'content':changed['content'],'expected_version':2}).json()['version']==2
    assert client.patch(path,json={'content':'并发旧草稿','expected_version':1}).status_code==409
    restored=client.patch(path,json={**{k:historic[k] for k in ('content','kind','tags')},'expected_version':2}).json()
    assert restored['version']==3 and restored['content']==note['content']
    assert client.get(path+'/revisions/2').json()['content']==changed['content']
    differences=client.get(path+'/revisions/2').json()['changes_to_current']
    assert len(differences)==1 and differences[0]['before']==changed['content'] and differences[0]['after']==note['content']
    assert [r['version'] for r in client.get(path+'/revisions').json()['items']]==[3,2,1]
    exported=client.get('/api/archive/export/json').json()
    assert len([r for r in exported['paper_note_revisions'] if r['note_id']==note['id']])==3
    assert client.get(path+'/revisions/9').status_code==404
    assert client.delete(path).status_code==204
    with Session(get_engine()) as s:assert not s.exec(select(PaperNoteRevision).where(PaperNoteRevision.note_id==note['id'])).all()


def test_agent_pagination_stays_on_snapshot_after_correction(client):
    pid,prefix,note=seed(client);path=f"{prefix}/{note['id']}";long='旧研究判断。'*1500
    client.patch(path,json={'content':long})
    with Session(get_engine()) as s:first=json.loads(read_paper_notes(s,pid,note['id'],max_chars=500))
    assert first['version']==2 and first['next_read']['version']==2
    client.patch(path,json={'content':'新研究判断。'})
    with Session(get_engine()) as s:
        parts=[first['text']];next_read=first['next_read']
        while next_read:
            args=dict(next_read);args.pop('tool')
            raw=read_paper_notes(s,**args);old=json.loads(raw)
            assert old['version']==2 and old['current_version']==3
            assert tool_sources(s,'read_paper_notes',raw)[0]['research_note']['version']==2
            parts.append(old['text']);next_read=old['next_read']
        assert ''.join(parts)==long
        assert json.loads(read_paper_notes(s,pid,note['id']))['text']=='新研究判断。'
        assert 'error' in json.loads(read_paper_notes(s,pid,note['id'],version=999))
    other=client.post('/api/papers/manual',json={'title':'Other source'}).json()['id']
    assert client.get(f'/api/papers/{other}/reading/notes/{note["id"]}/revisions/1').status_code==404


def test_note_history_follows_project_copy_independently(client):
    from test_workspace_copy import setup
    from app.workspaces.context import bind_workspace
    origin,target,_=setup(client)
    prefix=f'/api/w/{origin.id}/papers/1/reading/notes/1'
    assert client.patch(prefix,json={'content':'已核对笔记'}).json()['version']==2
    result=client.post(f'/api/w/{origin.id}/papers/1/copy-to-workspace',json={'target_workspace':target.id,'request_id':uuid4().hex,'include_notes':True})
    assert result.status_code==201,result.text
    with bind_workspace(target),Session(get_engine()) as s:
        revisions=s.exec(select(PaperNoteRevision).order_by(PaperNoteRevision.version)).all()
        assert [r.content for r in revisions]==['Interpretation in source','已核对笔记']
        nid=revisions[0].note_id
    copied=f'/api/w/{target.id}/papers/{result.json()["paper_id"]}/reading/notes/{nid}'
    client.patch(copied,json={'content':'目标项目追加判断'})
    assert client.get(prefix+'/revisions').json()['current_version']==2
    assert client.get(copied+'/revisions').json()['current_version']==3


def test_migration_preserves_legacy_note_exactly(tmp_path):
    from app.db.engine import make_engine
    from alembic.config import Config
    from alembic import command
    from app import paths
    from sqlalchemy import text
    engine=make_engine(tmp_path/'legacy.sqlite')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE papernote (id INTEGER PRIMARY KEY,paper_id INTEGER NOT NULL,kind TEXT NOT NULL,content TEXT NOT NULL,tags_json TEXT NOT NULL,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL)'))
        c.execute(text("INSERT INTO papernote VALUES (7,2,'note',:body,'[]','2026-01-01','2026-01-02')"),{'body':'旧精读卡😀\r\n\r\nPDF p. 3'})
    cfg=Config(str(paths.alembic_ini()));cfg.set_main_option('script_location',str(paths.migrations_dir()));cfg.set_main_option('sqlalchemy.url',str(engine.url))
    command.stamp(cfg,'ea51c09d1000');command.upgrade(cfg,'f0718b9c2001')
    with engine.connect() as c:
        current=c.execute(text('SELECT content,updated_at,version FROM papernote')).one()
        historic=c.execute(text('SELECT content,updated_at,version FROM papernoterevision')).one()
        assert current==historic==('旧精读卡😀\r\n\r\nPDF p. 3','2026-01-02',1)
