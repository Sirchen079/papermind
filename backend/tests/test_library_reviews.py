import json
import re
from types import SimpleNamespace
from uuid import uuid4
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Paper
from app.models.review import ReviewPaper, LibraryReview
from app.reviews import service


class FakeWriter:
    def __init__(self):self.calls=[];self.fail_paper=None;self.pause=None;self.card_calls=0
    def complete(self,provider,model,messages,**kwargs):
        # 精读卡片的调用不计入综述正文调用统计（卡 10）；解析失败即 fallback。
        if '论文精读卡片' in messages[0]['content']:
            self.card_calls+=1
            return SimpleNamespace(content='not-a-card')
        text=messages[-1]['content'];self.calls.append(text)
        if self.pause:
            callback=self.pause;self.pause=None;callback()
        if '逐篇分析。' in text:
            pid=int(re.search(r'"source": "P(\d+)"',text)[1])
            if pid==self.fail_paper:raise TimeoutError('test timeout')
            return SimpleNamespace(content=f'方法与结果 [P{pid}]：采用检索增强方法，评价条件需分别比较。')
        if '只输出标题列表' in text:return SimpleNamespace(content='研究问题\n方法比较\n结果与局限')
        if '仅返回需要修改的段落' in text:return SimpleNamespace(content='{"edits":[]}')
        refs=list(dict.fromkeys(re.findall(r'\[P\d+\]',text)))
        return SimpleNamespace(content='不同方法的结果需结合数据划分理解。'+' '.join(refs[:4])+'\n\n现有材料支持这一比较，不同设置不能直接排名。')


def setup(client,monkeypatch,count=3):
    with Session(get_engine()) as s:
        rows=[Paper(source='manual',title=f'Paper {i}',full_text=f'<!-- page:1 -->\nMethod {i} uses retrieval.\n<!-- page:2 -->\nEvaluation split S{i%3}; limitation is cost.') for i in range(count)]
        s.add_all(rows);s.commit();ids=[r.id for r in rows]
    fake=FakeWriter()
    monkeypatch.setattr(service,'pick_llm',lambda *_:(fake,SimpleNamespace(id=123,base_url='https://test.invalid'), 'fake'))
    monkeypatch.setattr('app.rag.scalable.hybrid',lambda *a,**k:[])
    response=client.post('/api/reviews',json={'request_id':str(uuid4()),'question':'检索方法综述','paper_ids':ids})
    assert response.status_code==201,response.text
    return '/api/reviews/'+response.json()['id'],fake,ids


def test_review_prose_output_missing_and_failure_do_not_block(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch)
    fake.fail_paper=ids[1]
    with Session(get_engine()) as s:
        row=s.get(Paper,ids[2]);row.full_text=None;s.add(row);s.commit()
    assert client.post(prefix+'/run').status_code==202
    result=client.get(prefix).json()
    assert result['status']=='ready',result
    assert result['counts']['done']==1
    assert result['counts']['fallback']==1
    assert result['counts']['missing']==1
    assert len(result['content'])>150
    assert len(result['sections'])==3
    assert all('analysis' not in row for row in result['papers'])
    assert client.get(prefix+f'/papers/{ids[0]}').json()['evidence'][0]['page']==1
    assert len(client.get(prefix+'/export?kind=coverage').text.splitlines())==3
    assert client.get(prefix+'/revisions/1').json()['content']==result['content']


def test_resume_reuse_incremental_source_change_and_revision(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch)
    client.post(prefix+'/run');first=client.get(prefix).json();calls=len(fake.calls)
    client.post(prefix+'/run');second=client.get(prefix).json()
    assert len(fake.calls)==calls
    assert second['counts']['reused']==3
    assert second['version']==1
    with Session(get_engine()) as s:
        p=s.get(Paper,ids[0]);p.full_text+='\nNew evidence: different evaluation.';s.add(p);s.commit()
    client.post(prefix+'/run')
    assert sum('逐篇分析。' in text for text in fake.calls[calls:])==1
    edited=client.post(prefix+'/content',json={'content':'研究者编辑后的综述','expected_version':client.get(prefix).json()['version']})
    assert edited.status_code==200
    assert client.get(prefix+'/revisions/1').json()['content']==first['content']
    assert client.post(prefix+'/content',json={'content':'过期编辑','expected_version':1}).status_code==409
    with Session(get_engine()) as s:
        new=Paper(source='manual',title='New paper',abstract='New retrieval method');s.add(new);s.commit();new_id=new.id
    added=client.post(prefix+'/papers',json={'paper_ids':[new_id]}).json()
    assert added['counts']['total']==4 and added['content']=='研究者编辑后的综述'
    previous=len(fake.calls);client.post(prefix+'/run')
    assert sum('逐篇分析。' in text for text in fake.calls[previous:])==1


def test_pause_restart_does_not_overwrite_and_can_continue(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch)
    fake.pause=lambda:client.post(prefix+'/stop')
    client.post(prefix+'/run')
    assert client.get(prefix).json()['status']=='paused'
    client.post(prefix+'/run')
    assert client.get(prefix).json()['status']=='ready'
    with Session(get_engine()) as s:service.start(s,prefix.rsplit('/',1)[1])
    service.recover_interrupted(get_engine())
    assert client.get(prefix).json()['status']=='paused'


def test_review_cache_tracks_changed_thinking_level_and_preserves_default_checkpoints(client,monkeypatch):
    from app.models import Provider, Model
    prefix,fake,ids=setup(client,monkeypatch)
    client.post(prefix+'/run')
    first_calls=len(fake.calls)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='Configured fake',type='openai_chat',base_url='https://test.invalid'))
        s.commit()
        model=Model(provider_id=123,model_id='fake',reasoning_effort='low')
        s.add(model);s.commit();mid=model.id
    client.post(prefix+'/run')
    assert len(fake.calls)==first_calls
    assert client.get(prefix).json()['counts']['reused']==len(ids)
    with Session(get_engine()) as s:
        model=s.get(Model,mid);model.reasoning_effort='high';s.add(model);s.commit()
    client.post(prefix+'/run')
    assert sum('逐篇分析。' in text for text in fake.calls[first_calls:])==len(ids)
    high_calls=len(fake.calls)
    client.post(prefix+'/run')
    assert len(fake.calls)==high_calls
    assert client.get(prefix).json()['counts']['reused']==len(ids)


def test_1000_paper_hierarchy_every_paper_accounted_for(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,1000)
    client.post(prefix+'/run')
    result=client.get(prefix).json()
    assert result['status']=='ready',result['error']
    assert result['counts']['done']==1000
    assert result['counts']['pending']==0
    assert sum('逐篇分析。' in text for text in fake.calls)==1000
    assert any('合并研究路线' in text for text in fake.calls)
    assert max(len(text) for text in fake.calls)<26000
    assert len(client.get(prefix+'/export?kind=coverage').text.splitlines())==1000


def test_citation_warning_preserves_prose():
    text,warning=service.clean_citations('有效 [P1]，错误 [P999]，后续正文。',{1})
    assert '[P1]' in text and '[P999]' not in text and '后续正文' in text and warning
    assert service.tolerant_text('```markdown\n可用正文\n```')=='可用正文'
    text,warning=service.clean_citations('组合 [P1, P2] 与 [P2、999]。',{1,2})
    assert text=='组合 [P1][P2] 与 [P2]〔来源待补〕。' and warning


def test_failed_chapter_keeps_bounded_material_and_full_paper_analyses(client,monkeypatch):
    from app.models import Provider,Model
    from app.agent.context import estimate_tokens
    prefix,fake,ids=setup(client,monkeypatch,18)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='large-window',type='openai_chat',base_url='https://test.invalid'));s.flush()
        s.add(Model(provider_id=123,model_id='fake',context_window=1000000));s.commit()
    original=fake.complete;failed=[True];calls=[]
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content'];calls.append(text)
        if '当前章节：研究问题。' in text and '只写当前章节' in text and failed[0]:
            raise TimeoutError('fixture chapter failure')
        result=original(provider,model,messages,**kwargs)
        if '逐篇分析。' in text:result.content+='\n\n'+('Mechanism evidence and evaluation conditions. '*300)+'ANALYSIS_END'
        if '只输出标题列表' in text:result.content='研究问题\n方法比较\n训练目标\n推理成本\n评价条件\n结果与局限'
        return result
    fake.complete=complete
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert result['status']=='ready'
    first=result['sections'][0]
    assert first['warning'] and '暂以已完成的研究材料' in first['content']
    assert estimate_tokens(first['content'])<=3600
    assert all(f'[P{pid}]' in first['content'] for pid in ids)
    assert any('完成整篇修订' in text for text in calls)
    assert not any('只返回这个片段的完整中文正文' in text for text in calls)
    with Session(get_engine()) as s:
        saved={p.paper_id:p.analysis for p in service.papers(s,result['id'])}
    assert all(text.endswith('ANALYSIS_END') for text in saved.values())
    assert sum(estimate_tokens(text) for text in saved.values())>16000
    count=sum('逐篇分析。' in text for text in calls)
    failed[0]=False
    client.post(prefix+'/run');updated=client.get(prefix).json()
    assert not updated['sections'][0]['warning']
    assert '暂以已完成的研究材料' not in updated['sections'][0]['content']
    assert sum('逐篇分析。' in text for text in calls)==count
    with Session(get_engine()) as s:
        assert {p.paper_id:p.analysis for p in service.papers(s,result['id'])}==saved


def test_review_rebudgets_exhausted_reasoning_without_losing_completed_work(client,monkeypatch):
    from app.models import Provider,Model
    from app.providers.client import EmptyResponseError
    from app.agent.context import total_tokens
    prefix,fake,ids=setup(client,monkeypatch,1)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='thinking',type='openai_responses',base_url='https://test.invalid'));s.flush()
        s.add(Model(provider_id=123,model_id='fake',reasoning_effort='high',context_window=32768));s.commit()
    original=fake.complete;caps=[]
    def complete(provider,model,messages,**kwargs):
        if '论文精读卡片' in messages[0]['content']:
            return original(provider,model,messages,**kwargs)  # 卡片调用不计入预算重试统计
        caps.append(kwargs['max_tokens'])
        assert total_tokens(messages)+caps[-1]<=32768
        if len(caps)==1:raise EmptyResponseError('empty',output_exhausted=True)
        return original(provider,model,messages,**kwargs)
    fake.complete=complete
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert caps[1]>caps[0]>=8192+1600
    assert result['status']=='ready' and result['counts']['done']==1
    count=len(caps)
    client.post(prefix+'/run')
    assert len(caps)==count


def test_group_synthesis_retains_late_results_and_qualifications(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,20)
    original=fake.complete;groups=[]
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '逐篇分析。' in text:
            pid=int(re.search(r'"source": "P(\d+)"',text)[1])
            return SimpleNamespace(content='\n\n'.join(
                f'{role}_{pid} [P{pid}] '+('较长的研究说明。'*180)
                for role in ('TASK','METHOD','RESULT_EXCEPTION','POSSIBLE_NOT_ESTABLISHED')))
        if '归纳本批论文' in text:groups.append(text)
        return original(provider,model,messages,**kwargs)
    fake.complete=complete
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert result['status']=='ready'
    assert len(groups)==1
    for pid in ids:
        assert f'RESULT_EXCEPTION_{pid}' in groups[0]
        assert f'POSSIBLE_NOT_ESTABLISHED_{pid}' in groups[0]


def test_review_background_workers_keep_workspace_and_sources_isolated(client,monkeypatch):
    from app.workspaces.context import bind_workspace
    contexts=[]
    for name in ('Review project A','Review project B'):
        wid=client.post('/api/workspaces',json={'name':name}).json()['id']
        context=client.app.state.workspaces.context(wid);contexts.append(context)
        with bind_workspace(context),Session(get_engine()) as s:
            s.add(Paper(source='manual',title=name,abstract=name+' retrieval results'));s.commit()
    seen=[]
    original=service.paper_evidence
    def capture(session,pid,question):
        from app.config import get_settings
        seen.append(get_settings().resolved_db_path)
        return original(session,pid,question)
    monkeypatch.setattr(service,'paper_evidence',capture)
    fake=FakeWriter()
    monkeypatch.setattr(service,'pick_llm',lambda *_:(fake,SimpleNamespace(id=123,base_url='https://test.invalid'),'fake'))
    monkeypatch.setattr('app.rag.scalable.hybrid',lambda *a,**k:[])
    a,b=['/api/w/'+c.id+'/reviews' for c in contexts]
    rid=str(uuid4())
    assert client.post(a,json={'request_id':rid,'question':'检索方法','whole_library':True}).status_code==201
    assert client.post(a+'/'+rid+'/run').status_code==202
    result=client.get(a+'/'+rid).json()
    assert result['status']=='ready' and result['counts']['done']==1
    assert result['papers'][0]['title']=='Review project A'
    assert client.get(b+'/'+rid).status_code==404
    assert client.get(b).json()==[]
    with bind_workspace(contexts[0]):
        from app.config import get_settings
        assert seen==[get_settings().resolved_db_path]
