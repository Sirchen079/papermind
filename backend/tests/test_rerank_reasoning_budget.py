import json
from types import SimpleNamespace
from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Model
from app.agent.context import total_tokens
from app.rag.reranking import apply, configuration
from test_llm_rerank import setup, add_papers


def test_shared_high_effort_model_has_room_and_time_to_return_ranking(client,monkeypatch):
    import litellm
    provider,mid=setup(client,'openai_responses')
    calls=[]
    def response(**kwargs):
        calls.append(kwargs)
        assert kwargs['max_output_tokens']>=8192+2048
        assert kwargs['timeout'].read>=180 and kwargs['num_retries']==0
        assert total_tokens(kwargs['input'])+kwargs['max_output_tokens']<=32768
        return SimpleNamespace(output_text='{"ranking":[1]}',status='completed',
                               usage={'input_tokens':100,'output_tokens':1000,'total_tokens':1100})
    monkeypatch.setattr(litellm,'responses',response)
    with Session(get_engine()) as s:
        model=s.get(Model,mid);model.reasoning_effort='high';model.context_window=32768;s.add(model);s.commit()
        a,b,_,_=add_papers(s)
        candidates=[(SimpleNamespace(paper_id=p.id,text=p.full_text),1.) for p in (a,b)]
        result=apply(s,'protein folding',candidates,1,configuration(s))
        assert calls and result[0][0].paper_id==b.id


def test_small_high_effort_ranking_stays_within_configured_context():
    from app.rag.llm_rerank import rank
    seen=[]
    def complete(provider,model,messages,**kwargs):
        seen.append(kwargs)
        assert total_tokens(messages)+kwargs['max_tokens']<=8192
        assert kwargs['max_tokens']>2048
        return SimpleNamespace(content=json.dumps({'ranking':[1,0]}))
    result=rank((SimpleNamespace(complete=complete),None,'small'),'中文查询',
                ['相关证据。'*1000]*2,2,8192,reasoning_effort='high')
    assert seen and [r[0] for r in result]==[1,0]
