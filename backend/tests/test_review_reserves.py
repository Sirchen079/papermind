import json
from concurrent.futures import ThreadPoolExecutor
from sqlmodel import Session,select
from app.db.engine import get_engine
from app.models.review import LibraryReview,ReviewSection
from app.reviews import reserves,service
from types import SimpleNamespace


def test_reserve_updates_merge_concurrent_models_and_never_decrease(client):
    engine=get_engine()
    with Session(engine) as s:s.add(LibraryReview(id='r',question='Test'));s.commit()
    values=[('a',9000),('b',14000),('a',18000),('a',12000)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item:reserves.increase(engine,'r',*item),values))
    with Session(engine) as s:
        assert reserves.load(s,'r')=={'a':18000,'b':14000}
        assert len(s.exec(select(ReviewSection)).all())==1
    provider=SimpleNamespace(id=1,base_url='https://test.invalid')
    assert reserves.model_key(provider,'m',32768,None)==service.digest([1,provider.base_url,'m',32768,'low'])


def test_reserve_hint_handles_legacy_bad_data_and_late_results(client):
    engine=get_engine()
    with Session(engine) as s:
        s.add(LibraryReview(id='r',question='Test',run_token='current'));s.flush()
        row=ReviewSection(review_id='r',ordinal=reserves.ORDINAL,title='metadata',fingerprint=reserves.FINGERPRINT,content='{bad')
        s.add(row);s.commit()
        assert reserves.load(s,'r')=={}
    reserves.increase(engine,'r','a',9000,run_token='old')
    with Session(engine) as s:assert reserves.load(s,'r')=={}
    reserves.increase(engine,'r','a',9000,run_token='current')
    reserves.increase(engine,'missing','a',9000)
    with Session(engine) as s:
        assert reserves.load(s,'r')=={'a':9000} and reserves.load(s,'missing')=={}
        row=s.exec(select(ReviewSection)).one();row.content=json.dumps({'a':9000,'b':True,'c':-1,'d':'bad'});s.add(row);s.commit()
        assert reserves.load(s,'r')=={'a':9000}


def test_generation_budget_is_available_to_paragraph_proposals(client,monkeypatch):
    from app.models import Provider,Model
    from app.reviews import editing
    from app.providers.client import EmptyResponseError
    from test_library_reviews import setup
    prefix,fake,ids=setup(client,monkeypatch,1)
    with Session(get_engine()) as s:
        provider=Provider(id=123,name='fixture',type='openai_chat',base_url='https://test.invalid')
        s.add(provider);s.flush()
        s.add(Model(provider_id=123,model_id='fake',context_window=1000000,reasoning_effort='high'));s.commit();s.refresh(provider)
    original=fake.complete;caps=[]
    def complete(*args,**kwargs):
        caps.append(kwargs['max_tokens'])
        if len(caps)==1:raise EmptyResponseError('fixture',output_exhausted=True)
        return original(*args,**kwargs)
    fake.complete=complete
    client.post(prefix+'/run');before=client.get(prefix).json();assert before['status']=='ready'
    monkeypatch.setattr(editing,'pick_llm',lambda *a:(fake,provider,'fake'))
    block=next(b for b in client.get(prefix+'/paragraphs').json()['blocks'] if '[P' in b['text'])
    assert client.post(prefix+'/paragraphs/propose',json={'expected_version':before['version'],'block_id':block['id'],'instruction':'精简'}).status_code==200
    assert caps[-1]>8192+600
    after=client.get(prefix).json();assert after['content']==before['content'] and after['version']==before['version']
