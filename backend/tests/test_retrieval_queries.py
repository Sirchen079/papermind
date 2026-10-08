import json
from types import SimpleNamespace
import pytest
from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Paper,PaperChunk
from app.rag.queries import variants
from app.rag.passages import with_context
from app.rag.vector import serialize
from app.reviews.evidence import chapter_sources


def test_translation_adds_query_and_never_replaces_original():
    calls=[]
    def complete(provider,model,messages,**kwargs):
        calls.append((messages,kwargs))
        return SimpleNamespace(content='How do 1-PAGER readers compare at 31.7 vs 34.2 EM?',output_incomplete=False)
    original='1-PAGER 的 31.7 与 34.2 是什么条件？'
    config=('llm',(SimpleNamespace(complete=complete),None,'text'))
    result=variants(original,config)
    assert result[0]==original and '31.7 vs 34.2' in result[1]
    assert calls[0][1]['request_kind']=='retrieval_query'
    assert len(calls)==1 and calls[0][0][1]['content']==original


@pytest.mark.parametrize('failure',['timeout','empty','incomplete'])
def test_translation_failure_does_not_block_original_retrieval(failure):
    def complete(*a,**kw):
        if failure=='timeout':raise TimeoutError()
        return SimpleNamespace(content='' if failure=='empty' else 'partial question',output_incomplete=failure=='incomplete')
    assert variants('中文问题',('llm',(SimpleNamespace(complete=complete),None,'text')))==['中文问题']


@pytest.mark.parametrize('query,mode',[('English only','llm'),('中文问题','dedicated'),('中文问题',None)])
def test_translation_does_not_add_calls_to_other_modes(query,mode):
    client=SimpleNamespace(complete=lambda *a,**kw:pytest.fail('Unexpected translation'))
    assert variants(query,(mode,(client,None,'text')) if mode else None)==[query]


def test_hybrid_keeps_original_and_translated_candidates_and_ranks_original_intent(client,monkeypatch):
    from app.rag import index,reranking,scalable
    a=SimpleNamespace(id=1,paper_id=1,text='Original-language evidence')
    b=SimpleNamespace(id=2,paper_id=2,text='English-language evidence')
    calls=[]
    monkeypatch.setattr(reranking,'configuration',lambda s:('llm',(SimpleNamespace(complete=lambda *a,**kw:SimpleNamespace(content='English query')),None,'text')))
    def retrieve(session,query,k,ids,**kwargs):
        calls.append((query,ids,kwargs));return [(a if query=='原问题' else b,1.)]
    monkeypatch.setattr(index,'retrieve',retrieve)
    monkeypatch.setattr(scalable,'lexical',lambda *a:[])
    def apply(session,query,candidates,k,config):
        assert query=='原问题' and {row.id for row,_ in candidates}=={1,2}
        return [(b,1),(a,.5)]
    monkeypatch.setattr(reranking,'apply',apply)
    assert scalable.hybrid(None,'原问题',[1,2],2)==[b,a]
    assert [c[0] for c in calls]==['原问题','English query']
    assert all(c[1]==[1,2] and c[2]=={'rerank':False} for c in calls)


def test_adjacent_evidence_keeps_cross_page_conditions_and_original_index(client):
    with Session(get_engine()) as session:
        paper=Paper(title='Study',source='manual');other=Paper(title='Other',source='manual')
        session.add_all([paper,other]);session.commit()
        texts=['Title and abstract','[第 23 页]\nSame Retriever but different Generator: 0.7 points on PopQA and 2.0',
               '[第 24 页]\npoints on TriviaQA. Conditions continue here.','[第 24 页]\nNext experiment.']
        chunks=[]
        for n,t in enumerate(texts):
            c=PaperChunk(paper_id=paper.id,ordinal=n,text=t,embedding_model='test',embedding=serialize([1,0]));chunks.append(c);session.add(c)
        session.add(PaperChunk(paper_id=other.id,ordinal=2,text='OUTSIDE',embedding_model='test',embedding=serialize([1,0])))
        session.commit()
        expanded=with_context(session,[chunks[1]])
        assert len(expanded)==1 and expanded[0].text.startswith(texts[1])
        assert texts[2] in expanded[0].text and texts[0] not in expanded[0].text and 'OUTSIDE' not in expanded[0].text
        assert chunks[1].text==texts[1]
        assert [s['page'] for s in expanded[0].context_segments]==[23,24]
        sources=chapter_sources([SimpleNamespace(paper_id=paper.id,evidence_json='[]')],expanded,'比较条件',1)
        assert sources[0]['page']==23 and 'TriviaQA' in sources[0]['quote']
        assert sources[0]['segments'][1]['page']==24
        assert with_context(session,[chunks[0]])==[chunks[0]]
        assert with_context(session,[])==[]


def test_adjacent_lookup_does_not_join_different_index_versions(client):
    with Session(get_engine()) as session:
        paper=Paper(title='Study',source='manual');session.add(paper);session.commit()
        anchor=PaperChunk(paper_id=paper.id,ordinal=1,text='[第 2 页]\nAnchor',embedding_model='new',embedding=serialize([1,0]))
        old=PaperChunk(paper_id=paper.id,ordinal=2,text='[第 3 页]\nOld context',embedding_model='old',embedding=serialize([1,0]))
        session.add_all([anchor,old]);session.commit()
        assert with_context(session,[anchor])==[anchor]
        stale=SimpleNamespace(paper_id=paper.id,ordinal=1,text='Old anchor')
        assert with_context(session,[stale])==[stale]
