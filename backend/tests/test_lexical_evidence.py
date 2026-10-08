from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Paper, PaperChunk
from app.rag.scalable import lexical
from app.rag.vector import serialize
from types import SimpleNamespace
import json


def test_decimal_conditions_find_results_instead_of_only_paper_introduction(client):
    with Session(get_engine()) as session:
        paper=Paper(title='NamedMethod',source='manual')
        outside=Paper(title='Outside scope',source='manual')
        deleted=Paper(title='Deleted',source='manual',is_deleted=True)
        session.add_all([paper,outside,deleted]);session.commit()
        texts=['NamedMethod introduction.',
               'With the same retriever, scores decrease by 0.7 and 2.0 points.',
               'Unrelated integer results 31 and 34.']
        for ordinal,text in enumerate(texts):
            session.add(PaperChunk(paper_id=paper.id,ordinal=ordinal,text=text,embedding_model='test',embedding=serialize([1,0])))
        for p in (outside,deleted):
            session.add(PaperChunk(paper_id=p.id,text=texts[1],embedding_model='test',embedding=serialize([1,0])))
        session.commit()
        hits=lexical(session,'NamedMethod 的 0.7 与 2.0 对应什么条件？',[paper.id,deleted.id])
        assert hits[0][0].ordinal==1
        assert all(row.paper_id==paper.id for row,_ in hits)
        assert [row.ordinal for row,_ in lexical(session,'0.7',[paper.id])]==[1]
        assert lexical(session,'0.7',[])==[]


def test_hyphenated_model_identifier_is_not_reduced_to_generic_words(client):
    with Session(get_engine()) as session:
        paper=Paper(title='Comparison',source='manual');session.add(paper);session.commit()
        for ordinal,text in enumerate(['A generic pager reports Recall@10.', '1-PAGER reports Recall@1.']):
            session.add(PaperChunk(paper_id=paper.id,ordinal=ordinal,text=text,embedding_model='test',embedding=serialize([1,0])))
        session.commit()
        hits=lexical(session,'1-PAGER',[paper.id])
        assert [row.ordinal for row,_ in hits]==[1]


def test_reranker_receives_paper_identity_for_anonymous_table_fragments(client,monkeypatch):
    from app.rag.reranking import apply
    from app.rag import llm_rerank
    with Session(get_engine()) as session:
        a=Paper(title='System Alpha: a retrieval study',source='manual')
        b=Paper(title='System Beta: a classification study',source='manual')
        session.add_all([a,b]);session.commit()
        chunks=[PaperChunk(paper_id=p.id,text='Table 2. baseline 31.7; improved 34.2.',embedding_model='test',embedding=serialize([1,0])) for p in (a,b)]
        session.add_all(chunks);session.commit()
        def choose(ctx,query,documents,k,window,**kwargs):
            assert all('Table 2.' in text for text in documents)
            wanted=next(i for i,text in enumerate(documents) if 'System Beta' in text)
            return [(wanted,1.0)]
        monkeypatch.setattr(llm_rerank,'rank',choose)
        result=apply(session,'System Beta comparison',[(c,.5) for c in chunks],1,('llm',(None,SimpleNamespace(id=1),'test')))
        assert result[0][0].paper_id==b.id


def test_large_window_reranker_retains_conditions_at_end_of_indexed_passage():
    from app.rag.llm_rerank import rank
    passage='Paper: Known system\nPassage:\n'+'Experiment background. '*48+'Same retriever; different generators; 2.0 point decrease.'
    def complete(provider,model,messages,**kwargs):
        payload=json.loads(messages[1]['content'])
        assert all(d['text']==passage for d in payload['candidates'])
        return SimpleNamespace(content='{"ranking":[0]}')
    assert rank((SimpleNamespace(complete=complete),None,'test'),'Known system conditions',[passage]*30,1,context_window=1048576)==[(0,1.0)]
