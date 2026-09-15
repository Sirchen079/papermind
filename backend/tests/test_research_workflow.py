import json
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Paper, ResearchTask
from app.research import service
from app.research.materials import collect_materials


@pytest.fixture
def research(client):
    with Session(get_engine()) as s:
        a=Paper(source='manual',title='Synthetic A',full_text='A uses split S1. No supervised labels are used.')
        b=Paper(source='manual',title='Synthetic B',abstract='B reports improvements; evaluation details unavailable.')
        s.add(a);s.add(b);s.commit();s.refresh(a);s.refresh(b);ids=[a.id,b.id]
    body={'request_id':str(uuid4()),'question':'Can we directly compare the methods?','paper_ids':ids,'depth':'evidence'}
    response=client.post('/api/research/tasks',json=body)
    assert response.status_code==201,response.text
    return response.json(),body


def save(client,task,content='Different conditions; cannot rank.',version=0):
    refs=[m['evidence'][0]['ref'] for m in task['materials']]
    return client.post(f"/api/research/tasks/{task['id']}/artifacts",json={'content':content,'expected_version':version,'evidence_refs':refs})


def test_no_project_creation_restore_and_idempotence(client,research):
    task,body=research
    assert task['project_id'] is None
    assert client.post('/api/research/tasks',json=body).json()['id']==task['id']
    assert client.post('/api/research/tasks',json={**body,'question':'Different goal'}).status_code==409
    assert client.get('/api/research/tasks/'+task['id']).json()['materials']==task['materials']
    assert client.post('/api/research/tasks/'+task['id']+'/run').status_code==422


def test_revision_invalidates_review_and_marks_reuse_stale(client,research):
    task,_=research;prefix='/api/research/tasks/'+task['id']
    saved=save(client,task).json();assert saved['artifact']['version']==1
    assert save(client,task).json()['artifact']['version']==1
    assert client.post(prefix+'/review',json={'expected_version':1,'status':'supported','note':''}).status_code==422
    reviewed=client.post(prefix+'/review',json={'expected_version':1,'status':'supported','note':'E1 and E2 establish different evaluation conditions.'}).json()
    assert reviewed['artifact']['version']==2
    assert client.post(prefix+'/adopt',json={'expected_version':2}).json()['artifact']['adopted']
    old=client.post(prefix+'/reuse',json={'expected_version':2,'kind':'meeting'}).json()
    assert not old['reuse'][0]['stale']
    changed=save(client,task,'A significantly outperforms B.',2).json()
    assert changed['artifact']['support_status']=='pending'
    assert changed['artifact']['adopted'] is False
    assert changed['reuse'][0]['stale']
    new=client.post(prefix+'/reuse',json={'expected_version':3,'kind':'meeting'}).json()
    assert '待核对' in new['reuse'][0]['content']
    assert '研究者已核对支持关系' not in new['reuse'][0]['content']
    assert save(client,task,'Stale edit',1).status_code==409


def test_invalid_refs_and_changed_source_rejected(client,research):
    task,_=research;prefix='/api/research/tasks/'+task['id']
    bad=client.post(prefix+'/artifacts',json={'expected_version':0,'content':'Invalid','evidence_refs':['E99']})
    assert bad.status_code==422
    save(client,task)
    with Session(get_engine()) as s:
        paper=s.get(Paper,task['paper_ids'][0]);paper.full_text='Updated content';s.add(paper);s.commit()
    response=client.post(prefix+'/review',json={'expected_version':1,'status':'supported','note':'Evidence read'})
    assert response.status_code==409


def test_old_source_snapshot_survives_material_refresh(client,research,monkeypatch):
    task,_=research;prefix='/api/research/tasks/'+task['id']
    initial=save(client,task).json()['artifact']['evidence_snapshot']
    with Session(get_engine()) as s:
        paper=s.get(Paper,task['paper_ids'][0]);paper.full_text='Replacement source with different conditions';s.add(paper);s.commit()
    fake_model(monkeypatch,FakeClient())
    client.post(prefix+'/run')
    new=client.post(prefix+'/reuse',json={'expected_version':1,'kind':'meeting'}).json()
    assert new['artifact']['evidence_snapshot']==initial
    assert 'No supervised labels' in new['reuse'][0]['content']
    assert '来源已变化' in new['reuse'][0]['content']


def test_reuse_preserves_evidence_after_original_paper_removed(client, research):
    task, _ = research
    saved = save(client, task).json()['artifact']
    with Session(get_engine()) as session:
        paper = session.get(Paper, task['paper_ids'][0])
        paper.is_deleted = True
        session.add(paper)
        session.commit()
    response = client.post('/api/research/tasks/' + task['id'] + '/reuse',
                           json={'expected_version': 1, 'kind': 'meeting'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['artifact']['evidence_snapshot'] == saved['evidence_snapshot']
    assert 'No supervised labels' in result['reuse'][0]['content']
    assert '已删除' in result['reuse'][0]['content']


class FakeClient:
    def __init__(self,callback=None): self.calls=0;self.callback=callback
    def complete(self,*args,**kwargs):
        self.calls+=1
        if self.callback:self.callback(self.calls)
        payload=json.loads(args[2][1]['content'])
        evidence=payload.get('material',{}).get('evidence') or [e for m in payload['materials'] for e in m['evidence']]
        result={'answer':'Conditions differ; this is a candidate judgment.','evidence_refs':[evidence[0]['ref']],'unknowns':['Controlled result missing'],'route':'conditions_mismatch','next_step':'Run matched evaluation; no experiment performed.'}
        return SimpleNamespace(content=json.dumps(result))


def fake_model(monkeypatch,client):
    monkeypatch.setattr(service,'pick_llm',lambda *args:(client,object(),'synthetic-model'))


def test_fixed_flow_and_resume_do_not_repeat_finished_steps(client,research,monkeypatch):
    task,_=research;fake=FakeClient();fake_model(monkeypatch,fake)
    prefix='/api/research/tasks/'+task['id']
    assert client.post(prefix+'/run').status_code==202
    data=client.get(prefix).json()
    assert fake.calls==3
    assert data['status']=='partial' and data['artifact']['support_status']=='pending'
    assert client.post(prefix+'/run').status_code==202
    assert fake.calls==3


def test_late_response_after_stop_is_discarded(client,research,monkeypatch):
    task,_=research
    def stop(_):
        with Session(get_engine()) as s:service.stop_task(s,task['id'])
    fake=FakeClient(stop);fake_model(monkeypatch,fake)
    client.post('/api/research/tasks/'+task['id']+'/run')
    data=client.get('/api/research/tasks/'+task['id']).json()
    assert fake.calls==1 and data['status']=='paused'
    assert data['steps']=={} and data['artifact'] is None


def test_restart_pauses_and_invalidates_running_token(client,research,monkeypatch):
    task,_=research;fake_model(monkeypatch,FakeClient())
    with Session(get_engine()) as s:token=service.start_task(s,task['id'])
    service.recover_interrupted(get_engine())
    with Session(get_engine()) as s:
        row=s.get(ResearchTask,task['id']);assert row.status=='paused' and row.run_token is None
    service.run_task(get_engine(),task['id'],token)
    assert client.get('/api/research/tasks/'+task['id']).json()['artifact'] is None


def test_quick_explanation_is_one_call(client,research,monkeypatch):
    _,body=research;fake=FakeClient();fake_model(monkeypatch,fake)
    task=client.post('/api/research/tasks',json={**body,'request_id':str(uuid4()),'depth':'quick'}).json()
    client.post('/api/research/tasks/'+task['id']+'/run')
    assert fake.calls==1


def test_generation_preserves_human_draft(client,research,monkeypatch):
    task,_=research;save(client,task,'My research decision.')
    fake_model(monkeypatch,FakeClient())
    client.post('/api/research/tasks/'+task['id']+'/run')
    result=client.get('/api/research/tasks/'+task['id']).json()
    assert result['artifact']['content']=='My research decision.'
    assert result['steps']['synthesis']['answer'].startswith('Conditions differ')


def test_failed_schema_is_bounded(client,research,monkeypatch):
    task,_=research
    class Invalid(FakeClient):
        def complete(self,*args,**kwargs):self.calls+=1;return SimpleNamespace(content='not JSON')
    fake=Invalid();fake_model(monkeypatch,fake)
    client.post('/api/research/tasks/'+task['id']+'/run')
    result=client.get('/api/research/tasks/'+task['id']).json()
    assert fake.calls==2 and result['status']=='partial' and result['artifact'] is None


def test_empty_final_response_retries_within_budget(client,research,monkeypatch):
    task,_=research
    class Empty(FakeClient):
        def complete(self,*args,**kwargs):
            self.calls+=1
            raise service.EmptyResponseError('No final text')
    fake=Empty();fake_model(monkeypatch,fake)
    client.post('/api/research/tasks/'+task['id']+'/run')
    result=client.get('/api/research/tasks/'+task['id']).json()
    assert fake.calls==2 and result['status']=='partial' and result['artifact'] is None


def test_appendix_selected_with_real_offsets(client):
    with Session(get_engine()) as s:
        text='background '*4000+'\nAppendix evaluation dataset split S9 baseline result.'
        paper=Paper(source='manual',title='Synthetic long paper',full_text=text)
        s.add(paper);s.commit();s.refresh(paper)
        materials=collect_materials(s,[paper.id],'evaluation dataset split')
        spans=[e for e in materials[0]['evidence'] if e['scope']=='full_text_span']
        assert any('S9' in e['quote'] for e in spans)
        for e in spans:assert text[e['start']:e['end']]==e['quote']


def test_single_json_fence_allowed_without_accepting_surrounding_prose():
    payload=json.dumps({'answer':'candidate','evidence_refs':['E1'],'unknowns':[],'route':'continue'})
    assert service.parse_output('```json\n'+payload+'\n```',{'E1'})['answer']=='candidate'
    with pytest.raises(ValueError):service.parse_output('Unsupported assertion\n'+payload,{'E1'})
