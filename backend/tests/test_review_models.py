from types import SimpleNamespace
from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Provider,Model
from app.providers.client import ProviderClient
from app.agent.context import total_tokens


def test_writer_switch_reuses_analysis_and_has_its_own_context(client,monkeypatch):
    from test_library_reviews import setup,FakeWriter
    prefix,analysis,ids=setup(client,monkeypatch)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='fixture',type='openai_chat',base_url='https://test.invalid'));s.flush()
        s.add(Model(provider_id=123,model_id='fake',role_default='chat',context_window=32768))
        writer=Model(provider_id=123,model_id='writer',context_window=8192,reasoning_effort='high')
        s.add(writer);s.commit();writer_id=writer.id
    client.post(prefix+'/run')
    original_analysis=sum('逐篇分析。' in text for text in analysis.calls)
    writer_calls=[];writing=FakeWriter()
    def complete(self,provider,model,messages,**kwargs):
        writer_calls.append(messages[-1]['content'])
        assert model=='writer'
        assert '逐篇分析。' not in messages[-1]['content']
        assert total_tokens(messages)+kwargs['max_tokens']<=8192
        return writing.complete(provider,model,messages,**kwargs)
    monkeypatch.setattr(ProviderClient,'complete',complete)
    key='/api/settings/review_writing_model_config_id'
    assert client.put(key,json={'value':str(writer_id)}).status_code==200
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert result['status']=='ready',result['error']
    assert result['counts']['reused']==len(ids)
    assert sum('逐篇分析。' in text for text in analysis.calls)==original_analysis
    assert any('仅返回需要修改的段落' in text for text in writer_calls)
    assert not any('归纳本批论文' in text or '只写当前章节' in text for text in writer_calls)
    count=len(writer_calls)
    client.post(prefix+'/run')
    assert len(writer_calls)==count
    new_id=client.post('/api/papers/manual',json={'title':'New evidence','abstract':'Additional retrieval evidence.'}).json()['id']
    client.post(prefix+'/papers',json={'paper_ids':[new_id]})
    client.post(prefix+'/run')
    assert client.get(prefix).json()['counts']['reused']==len(ids)
    assert sum('逐篇分析。' in text for text in analysis.calls)==original_analysis+1
    original_analysis+=1
    count=len(writer_calls)
    with Session(get_engine()) as s:
        row=s.get(Model,writer_id);row.reasoning_effort='medium';s.add(row);s.commit()
    client.post(prefix+'/run')
    assert len(writer_calls)>count
    assert sum('逐篇分析。' in text for text in analysis.calls)==original_analysis
    count=len(writer_calls)
    # Clearing the override restores the default without invalidating analyses.
    assert client.put(key,json={'value':''}).status_code==200
    client.post(prefix+'/run')
    assert client.get(prefix).json()['status']=='ready'
    assert sum('逐篇分析。' in text for text in analysis.calls)==original_analysis
    assert len(writer_calls)==count


def test_writer_is_project_scoped_and_accepts_only_available_text_models(client):
    a=client.post('/api/workspaces',json={'name':'Writing A'}).json()['id']
    b=client.post('/api/workspaces',json={'name':'Writing B'}).json()['id']
    prefix=f'/api/w/{a}'
    pid=client.post(prefix+'/providers',json={'name':'writer','type':'openai_chat'}).json()['id']
    mid=client.post(prefix+f'/providers/{pid}/models',json={'model_id':'writer'}).json()['id']
    embedding=client.post(prefix+f'/providers/{pid}/models',json={'model_id':'embedding','role_default':'embedding'}).json()['id']
    key='/settings/review_writing_model_config_id'
    assert client.put(prefix+key,json={'value':str(mid)}).status_code==200
    assert 'review_writing_model_config_id' not in client.get(f'/api/w/{b}/settings').json()
    for value in ('bad','-1','999999',str(embedding)):
        assert client.put(prefix+key,json={'value':value}).status_code==422
    assert client.get(prefix+'/settings').json()['review_writing_model_config_id']==str(mid)


def test_paragraph_proposal_uses_selected_writer_without_saving(client,monkeypatch):
    from test_review_editing import seed
    prefix,original=seed(client)
    provider=client.post('/api/providers',json={'name':'writer','type':'openai_chat'}).json()['id']
    model=client.post(f'/api/providers/{provider}/models',json={'model_id':'selected-writer'}).json()['id']
    client.put('/api/settings/review_writing_model_config_id',json={'value':str(model)})
    calls=[]
    def complete(self,provider,model,messages,**kwargs):
        calls.append(model);return SimpleNamespace(content='依据原文修正后的正文 [P7]。')
    monkeypatch.setattr(ProviderClient,'complete',complete)
    block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    response=client.post(prefix+'/paragraphs/propose',json={'expected_version':1,'block_id':block['id'],'instruction':'核对原文'})
    assert response.status_code==200,response.text
    assert calls==['selected-writer']
    assert client.get(prefix).json()['content']==original


def test_output_recovery_is_reused_across_phases_but_not_models_or_new_reviews(client,monkeypatch):
    from uuid import uuid4
    from test_library_reviews import setup,FakeWriter
    from app.providers.client import EmptyResponseError
    prefix,analysis,ids=setup(client,monkeypatch,count=1)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='fixture',type='openai_chat',base_url='https://test.invalid'));s.flush()
        s.add(Model(provider_id=123,model_id='fake',role_default='chat',context_window=32768,reasoning_effort='high'))
        writer=Model(provider_id=123,model_id='writer',context_window=32768,reasoning_effort='low')
        s.add(writer);s.commit();writer_id=writer.id
    client.put('/api/settings/review_writing_model_config_id',json={'value':str(writer_id)})
    original=analysis.complete;analysis_caps=[];writer_calls=[];writing=FakeWriter()
    def analyze(*args,**kwargs):
        analysis_caps.append(kwargs['max_tokens'])
        if len(analysis_caps)==1:raise EmptyResponseError('fixture',output_exhausted=True)
        return original(*args,**kwargs)
    analysis.complete=analyze
    def write(self,provider,model,messages,**kwargs):
        assert model=='writer'
        assert total_tokens(messages)+kwargs['max_tokens']<=32768
        writer_calls.append((messages[-1]['content'],kwargs['max_tokens']))
        if len(writer_calls)==1:return SimpleNamespace(content='部分综合',output_incomplete=True,output_exhausted=True)
        return writing.complete(provider,model,messages,**kwargs)
    monkeypatch.setattr(ProviderClient,'complete',write)
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert result['status']=='ready' and not result['error']
    assert len(analysis_caps)==2 and analysis_caps[1]>analysis_caps[0]
    assert writer_calls[0][1]<analysis_caps[0]  # Analysis model's learned reserve stays separate.
    assert writer_calls[1][1]>writer_calls[0][1]
    chapter_caps=[cap for text,cap in writer_calls if '只写当前章节' in text]
    assert chapter_caps and all(cap>3500 for cap in chapter_caps)
    calls=len(writer_calls)
    client.post(prefix+'/run');assert len(writer_calls)==calls
    # A fresh review reuses paper analyses, but starts its own output allowance.
    second=client.post('/api/reviews',json={'request_id':str(uuid4()),'question':result['question'],'paper_ids':ids}).json()['id']
    client.post(f'/api/reviews/{second}/run')
    assert writer_calls[calls][1]==writer_calls[0][1]
    assert len(analysis_caps)==2


def test_failed_chapter_resume_remembers_output_budget_without_reanalyzing(client,monkeypatch):
    import json
    from test_library_reviews import setup
    from app.providers.client import EmptyResponseError
    from app.models.review import ReviewSection
    from sqlmodel import select
    prefix,fake,ids=setup(client,monkeypatch,1)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='fixture',type='openai_chat',base_url='https://test.invalid'));s.flush()
        model=Model(provider_id=123,model_id='fake',reasoning_effort='high',context_window=1000000)
        s.add(model);s.commit();mid=model.id
    original=fake.complete;caps=[];analysis=[];updates=[]
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '逐篇分析。' in text:analysis.append(text)
        if '仅返回需要修改的段落' in text:
            updates.append((messages,kwargs['max_tokens']))
        if '当前章节：研究问题。' in text and '只写当前章节' in text:
            caps.append(kwargs['max_tokens'])
            if len(caps)<=2:raise EmptyResponseError('fixture',output_exhausted=True)
        return original(provider,model,messages,**kwargs)
    fake.complete=complete
    client.post(prefix+'/run');first=client.get(prefix).json()
    assert first['status']=='ready' and first['sections'][0]['warning']
    assert len(caps)==2 and caps[1]>caps[0]
    with Session(get_engine()) as s:
        meta=s.exec(select(ReviewSection).where(ReviewSection.review_id==first['id'],ReviewSection.ordinal==-99995)).one()
        assert max(json.loads(meta.content).values())>caps[1]
    # A fresh run has a new in-memory reserve map and must load its checkpoint.
    client.post(prefix+'/run');second=client.get(prefix).json()
    assert second['status']=='ready' and not second['sections'][0]['warning']
    assert len(caps)==3 and caps[2]>caps[1]
    assert len(analysis)==1 and second['counts']['reused']==1
    assert all(s['ordinal']>=0 for s in second['sections'])
    # Context changes identify a new configuration, so the previous allowance
    # cannot crowd its smaller input window before an actual exhausted response.
    with Session(get_engine()) as s:
        row=s.get(Model,mid);row.context_window=65536;s.add(row);s.commit()
    client.post(prefix+'/run')
    # A completed manuscript now takes the targeted-update path. Changing the
    # context must reset its allowance without regenerating old chapters.
    assert len(caps)==3 and len(updates)==1
    from app.agent.context import estimate_tokens
    from app.providers.output_budget import response_budget
    import re
    messages,cap=updates[0]
    target=re.search(r'目标段落：\n([^\n]+)',messages[-1]['content'])[1]
    assert cap==response_budget(65536,max(1200,min(6000,estimate_tokens(target))),'high')
    assert total_tokens(messages)+cap<=65536
