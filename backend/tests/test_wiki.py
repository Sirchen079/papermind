import json
from types import SimpleNamespace
from uuid import uuid4
from fastapi.testclient import TestClient


def create_page(client, prefix='/api', title='基线选择与评测条件'):
    response=client.post(prefix+'/wiki/pages',json={'request_id':str(uuid4()),'title':title})
    assert response.status_code==201,response.text
    return response.json()


def paper(client,prefix='/api',title='Baseline evaluation evidence',abstract='Baseline evaluation conditions and limitations.'):
    response=client.post(prefix+'/papers/manual',json={'title':title,'abstract':abstract})
    assert response.status_code==201,response.text
    return response.json()['id']


def save(client,page,content='基线选择取决于评测条件。',prefix='/api',**extra):
    body={'request_id':str(uuid4()),'expected_version':page['version'],'content':content,**extra}
    response=client.post(prefix+f"/wiki/pages/{page['id']}/revisions",json=body)
    assert response.status_code==200,response.text
    return response.json(),body


def configure(client,prefix='/api'):
    provider=client.post(prefix+'/providers',json={'name':'Wiki synthetic','type':'openai_chat'}).json()
    assert client.post(prefix+f"/providers/{provider['id']}/models",json={'model_id':'synthetic','role_default':'chat'}).status_code==201


def mock_complete(self,provider,model,messages,**kwargs):
    payload=json.loads(messages[1]['content'])
    ref=payload['model_evidence'][0]['ref']
    return SimpleNamespace(content=json.dumps({'content':f'基线评测需要核对条件。[{ref}]','references':[ref],'change_note':'纳入新增证据并整理条件。'},ensure_ascii=False))


def test_long_history_reads_one_exact_revision_without_loading_all_full_texts(client):
    page=create_page(client,title='Versioned topic')
    content='Archived version evidence. '*500
    page,_=save(client,page,content=content+' v1')
    page=client.post(f"/api/wiki/pages/{page['id']}/adopt",json={'expected_version':page['version'],'number':1}).json()
    for number in range(2,11):
        page,_=save(client,page,content=content+f' v{number}')
    response=client.get('/api/wiki/pages/'+page['id'])
    assert response.status_code==200
    assert len(response.content)<50000  # Old behavior duplicated ten full snapshots here.
    assert [r['number'] for r in response.json()['history']]==list(range(10,0,-1))
    for number in (1,4,10):
        historical=client.get(f"/api/wiki/pages/{page['id']}/revisions/{number}")
        assert historical.status_code==200
        assert historical.json()['content']==content+f' v{number}'
    assert client.get(f"/api/wiki/pages/{page['id']}/revisions/99").status_code==404
    assert client.get(f"/api/wiki/pages/{uuid4()}/revisions/1").status_code==404


def test_list_searches_latest_text_but_chat_searches_only_adopted_text(client):
    empty=create_page(client,title='Unwritten topic')
    page=create_page(client,title='Comparison conditions')
    page,_=save(client,page,content='quartz adopted evidence')
    page=client.post(f"/api/wiki/pages/{page['id']}/adopt",json={'expected_version':page['version'],'number':1}).json()
    page,_=save(client,page,content='zircon candidate evidence')
    summaries=client.get('/api/wiki/pages').json()
    assert next(row for row in summaries if row['id']==empty['id'])['latest_number'] is None
    summary=next(row for row in summaries if row['id']==page['id'])
    assert summary['latest_number']==2 and summary['preview']=='zircon candidate evidence'
    assert client.get('/api/wiki/pages',params={'q':'zircon'}).json()[0]['id']==page['id']
    assert client.get('/api/wiki/search',params={'q':'zircon'}).json()==[]
    hits=client.get('/api/wiki/search',params={'q':'quartz'}).json()
    assert len(hits)==1 and hits[0]['revision']==1 and hits[0]['content']=='quartz adopted evidence'


def test_manual_revisions_adoption_retries_and_deleted_source_export(client):
    pid=paper(client)
    page=create_page(client)
    assert client.get('/api/wiki/search',params={'q':'基线'}).json()==[]
    page,body=save(client,page,paper_ids=[pid],cite_added=True)
    first=page['latest'];ref=first['references'][0]
    repeated=client.post(f"/api/wiki/pages/{page['id']}/revisions",json=body).json()
    assert len(repeated['history'])==1
    adopted=client.post(f"/api/wiki/pages/{page['id']}/adopt",json={'expected_version':page['version'],'number':1}).json()
    assert adopted['adopted']['number']==1
    revised,_=save(client,adopted,content='新的候选判断，等待检查。',references=[ref])
    assert revised['adopted']['content']==first['content']
    assert revised['latest']['number']==2
    hits=client.get('/api/wiki/search',params={'q':'基线评测'}).json()
    assert hits[0]['revision']==1
    assert hits[0]['content']==first['content']
    conflict=client.post(f"/api/wiki/pages/{page['id']}/revisions",json={**body,'request_id':str(uuid4()),'content':'Stale editor'})
    assert conflict.status_code==409
    assert client.delete('/api/papers/'+str(pid)).status_code==204
    changed=client.get(f"/api/wiki/pages/{page['id']}").json()
    assert '移除' in changed['changes'][0]['reason']
    exported=client.get(f"/api/wiki/pages/{page['id']}/export",params={'number':1})
    assert exported.status_code==200
    assert 'Baseline evaluation conditions' in exported.text
    assert '原论文已移除' in exported.text


def test_stable_refs_change_with_source_version_and_cumulative_batches_exceed_five_papers(client):
    page=create_page(client)
    for batch in range(2):
        ids=[paper(client,title=f'Batch {batch} paper {i}') for i in range(4)]
        page,_=save(client,page,paper_ids=ids,cite_added=True,references=page['latest']['references'] if page['latest'] else [])
    assert len({e['paper_id'] for e in page['latest']['evidence']})==8
    original=page['latest']['evidence'][0]
    client.patch('/api/papers/'+str(original['paper_id']),json={'abstract':'Changed evaluation settings'})
    updated,_=save(client,page,paper_ids=[original['paper_id']],cite_added=True,references=page['latest']['references'])
    versions=[e for e in updated['latest']['evidence'] if e['paper_id']==original['paper_id']]
    assert len({e['ref'] for e in versions})==2
    assert original in updated['latest']['evidence']
    assert updated['changes']
    invalid=client.post(f"/api/wiki/pages/{page['id']}/revisions",json={'request_id':str(uuid4()),'expected_version':updated['version'],'content':'Unsupported','references':['W'+'0'*24]})
    assert invalid.status_code==422


def test_model_update_keeps_adoption_and_rejects_invented_references(client,monkeypatch):
    configure(client);pid=paper(client);page=create_page(client)
    page,_=save(client,page,paper_ids=[pid],cite_added=True)
    page=client.post(f"/api/wiki/pages/{page['id']}/adopt",json={'expected_version':page['version'],'number':1}).json()
    monkeypatch.setattr('app.providers.client.ProviderClient.complete',mock_complete)
    request={'request_id':str(uuid4()),'expected_version':page['version'],'paper_ids':[pid]}
    response=client.post(f"/api/wiki/pages/{page['id']}/updates",json=request)
    assert response.status_code==202,response.text
    after=client.get(f"/api/wiki/pages/{page['id']}").json()
    assert after['latest']['origin']=='model'
    assert after['adopted']['number']==1
    assert after['updates'][0]['status']=='done'
    assert client.post(f"/api/wiki/pages/{page['id']}/updates",json=request).json()['status']=='done'
    monkeypatch.setattr('app.providers.client.ProviderClient.complete',lambda *a,**k:SimpleNamespace(content=json.dumps({'content':'Invented [W'+'0'*24+']','references':['W'+'0'*24],'change_note':'Bad'})))
    failure=client.post(f"/api/wiki/pages/{page['id']}/updates",json={'request_id':str(uuid4()),'expected_version':after['version']}).json()
    assert client.get('/api/wiki/updates/'+failure['id']).json()['status']=='failed'
    assert client.get(f"/api/wiki/pages/{page['id']}").json()['latest']['number']==2


def test_model_result_survives_concurrent_human_edit_without_overwriting_it(client,monkeypatch):
    configure(client);pid=paper(client);page=create_page(client)
    page,_=save(client,page,paper_ids=[pid],cite_added=True)
    def slow(self,provider,model,messages,**kwargs):
        saved,_=save(client,page,content='人工在模型运行期间补充的结论。',references=page['latest']['references'])
        assert saved['latest']['number']==2
        return mock_complete(self,provider,model,messages,**kwargs)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete',slow)
    response=client.post(f"/api/wiki/pages/{page['id']}/updates",json={'request_id':str(uuid4()),'expected_version':page['version']})
    assert response.status_code==202,response.text
    after=client.get(f"/api/wiki/pages/{page['id']}").json()
    assert after['latest']['content']=='人工在模型运行期间补充的结论。'
    assert after['updates'][0]['status']=='conflict'
    assert after['updates'][0]['result']['content'].startswith('基线评测')
    job=after['updates'][0]
    body={'request_id':str(uuid4()),'expected_version':after['version']}
    path='/api/wiki/updates/'+job['id']+'/save-candidate'
    retained=client.post(path,json=body)
    assert retained.status_code==200,retained.text
    result=retained.json()
    historical=client.get(f"/api/wiki/pages/{page['id']}/revisions/{result['history'][1]['number']}")
    assert historical.status_code==200
    assert historical.json()['content']=='人工在模型运行期间补充的结论。'
    assert result['latest']['references']==job['result']['references']
    assert all(ref in {e['ref'] for e in result['latest']['evidence']} for ref in result['latest']['references'])
    assert len(client.post(path,json=body).json()['history'])==3


def test_adopted_topics_and_same_ids_are_scoped_to_workspace(client):
    a=client.post('/api/workspaces',json={'name':'A'}).json()['id']
    b=client.post('/api/workspaces',json={'name':'B'}).json()['id']
    same_id=str(uuid4())
    for wid,content in ((a,'A 项目私有基线判断'),(b,'B 项目私有基线判断')):
        prefix='/api/w/'+wid
        page=client.post(prefix+'/wiki/pages',json={'request_id':same_id,'title':'基线选择'}).json()
        page,_=save(client,page,content=content,prefix=prefix)
        assert client.post(prefix+f'/wiki/pages/{same_id}/adopt',json={'expected_version':page['version'],'number':1}).status_code==200
    result=client.get('/api/w/'+a+'/wiki/search',params={'q':'基线'}).json()
    assert result[0]['content']=='A 项目私有基线判断'
    assert client.get('/api/wiki/pages').json()==[]
    archived=client.patch('/api/w/'+a+'/wiki/pages/'+same_id,json={'expected_version':2,'archived':True})
    assert archived.status_code==200
    assert client.get('/api/w/'+a+'/wiki/search',params={'q':'基线'}).json()==[]
    assert client.get('/api/w/'+b+'/wiki/search',params={'q':'基线'}).json()[0]['content']=='B 项目私有基线判断'


def test_quoted_topic_retains_version_and_detects_transitive_source_changes(client):
    pid=paper(client);first=create_page(client)
    first,_=save(client,first,paper_ids=[pid],cite_added=True)
    client.post(f"/api/wiki/pages/{first['id']}/adopt",json={'expected_version':first['version'],'number':1})
    second=create_page(client,title='引用已有专题的条件')
    second,_=save(client,second,page_refs=[{'page_id':first['id'],'number':1}],cite_added=True)
    original=second['latest']['evidence'][0]
    client.patch('/api/papers/'+str(pid),json={'abstract':'Source changed'})
    checked=client.get(f"/api/wiki/pages/{second['id']}").json()
    assert checked['changes']
    assert checked['latest']['evidence'][0]==original


def test_interrupted_update_can_retry_and_remains_a_candidate(client,monkeypatch):
    from app.wiki import service
    from app.db.engine import get_engine
    from sqlmodel import Session
    configure(client);pid=paper(client);page=create_page(client)
    with Session(get_engine()) as session:
        job,launch=service.start_update(session,page['id'],str(uuid4()),0,[pid],[])
        assert launch
    service.recover_interrupted(get_engine())
    assert client.get('/api/wiki/updates/'+job['id']).json()['status']=='interrupted'
    monkeypatch.setattr('app.providers.client.ProviderClient.complete',mock_complete)
    assert client.post('/api/wiki/updates/'+job['id']+'/retry').status_code==202
    after=client.get(f"/api/wiki/pages/{page['id']}").json()
    assert after['updates'][0]['status']=='done'
    assert after['adopted'] is None


def test_research_artifact_into_topic_then_chat_receives_versioned_evidence(client,monkeypatch):
    from app.providers.client import ToolTurn
    configure(client);pid=paper(client)
    task=client.post('/api/research/tasks',json={'request_id':str(uuid4()),'question':'基线评测的适用条件','paper_ids':[pid]}).json()
    ref=task['materials'][0]['evidence'][0]['ref']
    task=client.post('/api/research/tasks/'+task['id']+'/artifacts',json={'expected_version':0,'content':'统一评测条件后再比较基线。','evidence_refs':[ref]}).json()
    topic=create_page(client)
    topic,_=save(client,topic,content=task['artifact']['content'],artifact_ids=[task['artifact']['id']],cite_added=True)
    snapshot=topic['latest']['evidence'][0]
    assert snapshot['underlying_evidence'][0]['quote'].startswith('Baseline evaluation')
    assert client.post(f"/api/wiki/pages/{topic['id']}/adopt",json={'expected_version':topic['version'],'number':1}).status_code==200
    def complete(self,provider,model,messages,request_kind,**kwargs):
        text=str(messages)
        assert '统一评测条件后再比较基线' in text
        assert topic['id'] in text and 'revision=1' in text
        assert 'Baseline evaluation' in text
        assert 'researcher_judgment' in text
        return ToolTurn('已核对所提供的专题版本。',[],1,1,2)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools',complete)
    monkeypatch.setattr('app.rag.index.retrieve',lambda *a,**k:[])
    conv=client.post('/api/chat/conversations').json()['id']
    answer=client.post(f'/api/chat/conversations/{conv}/messages',json={'content':'基线评测应该看哪些条件？'})
    assert answer.status_code==200,answer.text
    from sqlmodel import Session
    from app.db.engine import get_engine
    from app.agent.tools import get_tool
    with Session(get_engine()) as session:
        result=json.loads(get_tool('search_topic_wiki').run(session,query='基线评测'))
        assert result[0]['page_id']==topic['id']
        assert result[0]['revision']==1


def test_topic_copy_detaches_foreign_ids_retains_nested_sources_and_retries(client):
    from concurrent.futures import ThreadPoolExecutor
    a=client.post('/api/workspaces',json={'name':'Source'}).json()['id']
    b=client.post('/api/workspaces',json={'name':'Destination'}).json()['id']
    pa='/api/w/'+a;pb='/api/w/'+b
    pid=paper(client,pa);assert paper(client,pb,abstract='Unrelated destination paper')==pid
    first=create_page(client,pa)
    first,_=save(client,first,prefix=pa,paper_ids=[pid],cite_added=True)
    second=create_page(client,pa,title='基线概括')
    second,_=save(client,second,prefix=pa,page_refs=[{'page_id':first['id'],'number':1}],cite_added=True)
    ref=second['latest']['references'][0]
    second,_=save(client,second,prefix=pa,content=f'基线条件 [{ref}]',references=[ref])
    path=pa+'/wiki/pages/'+second['id']+'/copy-to-workspace'
    body={'target_workspace':b,'number':2,'request_id':str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:client.post(path,json=body),range(2)))
    assert all(r.status_code==201 for r in responses),[r.text for r in responses]
    assert sorted(r.json()['reused'] for r in responses)==[False,True]
    copied=client.get(pb+'/wiki/pages/'+responses[0].json()['page_id']).json()
    assert copied['adopted'] is None and copied['latest']['support_status']=='pending'
    assert copied['copied_from']['source_revision']==2
    assert copied['changes']==[]
    assert copied['latest']['references'][0]!=ref
    assert '['+copied['latest']['references'][0]+']' in copied['latest']['content']
    def check(entries):
        for entry in entries:
            assert 'dependency' not in entry and 'paper_id' not in entry
            assert entry['captured_from']['workspace']==a
            check(entry.get('underlying_evidence',[]))
    check(copied['latest']['evidence'])
    client.delete(pa+'/papers/'+str(pid));client.delete(pb+'/papers/'+str(pid))
    assert client.get(pb+'/wiki/pages/'+copied['id']).json()['changes']==[]
    exported=client.get(pb+'/wiki/pages/'+copied['id']+'/export?number=1').text
    assert 'Baseline evaluation conditions' in exported and 'Source' in exported
    assert client.post(path,json={**body,'number':1}).status_code==409
    assert client.post(path,json={**body,'target_workspace':a}).status_code==409
    client.patch('/api/workspaces/'+b,json={'archived':True})
    assert client.post(path,json=body).status_code==409


def test_nested_research_sources_still_report_changes_after_flattening(client):
    pid=paper(client)
    task=client.post('/api/research/tasks',json={'request_id':str(uuid4()),'question':'基线证据','paper_ids':[pid]}).json()
    task=client.post('/api/research/tasks/'+task['id']+'/artifacts',json={'expected_version':0,'content':'基线结论','evidence_refs':[task['materials'][0]['evidence'][0]['ref']]}).json()
    topic=create_page(client)
    topic,_=save(client,topic,artifact_ids=[task['artifact']['id']],cite_added=True)
    for i in range(4):
        cited=create_page(client,title='引用层 '+str(i))
        cited,_=save(client,cited,page_refs=[{'page_id':topic['id'],'number':1}],cite_added=True)
        topic=cited
    snapshot=topic['latest']['evidence'][0]
    assert all('underlying_evidence' not in e for e in snapshot['underlying_evidence'])
    client.delete('/api/papers/'+str(pid))
    result=client.get('/api/wiki/pages/'+topic['id']).json()
    assert any('原论文已移除' in c['reason'] for c in result['changes'])
    assert 'Baseline evaluation conditions' in client.get('/api/wiki/pages/'+topic['id']+'/export?number=1').text


def test_model_update_caps_chinese_materials_to_selected_context_window(client,monkeypatch):
    from app.agent.context import estimate_tokens
    from app.models import Model
    from app.db.engine import get_engine
    from sqlmodel import Session,select
    configure(client)
    with Session(get_engine()) as session:
        model=session.exec(select(Model)).first();model.context_window=8000;session.add(model);session.commit()
    ids=[paper(client,title='中文材料 '+str(i),abstract='中文科研证据与适用条件。'*300) for i in range(20)]
    topic=create_page(client)
    def limited(self,provider,model,messages,**kwargs):
        assert estimate_tokens(''.join(m['content'] for m in messages))+kwargs['max_tokens']<8000
        payload=json.loads(messages[-1]['content'])
        assert payload['omitted_evidence_count']>0
        return mock_complete(self,provider,model,messages,**kwargs)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete',limited)
    response=client.post('/api/wiki/pages/'+topic['id']+'/updates',json={'request_id':str(uuid4()),'expected_version':topic['version'],'paper_ids':ids})
    assert response.status_code==202,response.text
    topic=client.get('/api/wiki/pages/'+topic['id']).json()
    assert topic['updates'][0]['status']=='done',topic['updates']
    assert len({e['paper_id'] for e in topic['latest']['evidence']})==20
    topic,_=save(client,topic,content='中文长篇判断。'*1700)
    response=client.post('/api/wiki/pages/'+topic['id']+'/updates',json={'request_id':str(uuid4()),'expected_version':topic['version']})
    assert response.status_code==422 and '上下文' in response.text
