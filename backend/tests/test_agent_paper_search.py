import json
from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Paper, PaperChunk
from app.rag.vector import serialize
from app.agent.tools import get_tool
from app.agent.provenance import tool_sources


def test_agent_searches_passages_with_scope_and_cross_page_context(client):
    with Session(get_engine()) as s:
        a=Paper(title='A',source='manual');b=Paper(title='B',source='manual')
        deleted=Paper(title='Removed',source='manual',is_deleted=True)
        s.add_all([a,b,deleted]);s.commit()
        for p,n,text in [(a,0,'A metadata'),(a,1,'[第 23 页]\nFixed retriever: 0.7 PopQA and 2.0'),
                         (a,2,'[第 24 页]\npoints on TriviaQA with a different generator.'),
                         (b,1,'[第 2 页]\nFixed retriever with OUTSIDE data'),
                         (deleted,1,'[第 2 页]\nFixed retriever DELETED')]:
            s.add(PaperChunk(paper_id=p.id,ordinal=n,text=text,embedding=serialize([1,0]),embedding_model='fixture'))
        s.commit()
        tool=get_tool('search_paper_text')
        # No configured vector provider: existing local keyword recall is usable.
        raw=tool.run(s,query='fixed retriever',paper_ids=[a.id],top_k=1)
        rows=json.loads(raw)
        assert len(rows)==1 and rows[0]['paper_id']==a.id
        assert rows[0]['pages']==[23,24] and 'TriviaQA' in rows[0]['text']
        assert 'OUTSIDE' not in raw and 'DELETED' not in raw
        provenance=tool_sources(s,'search_paper_text',raw)
        assert provenance[0]['source_type']=='full_text' and provenance[0]['locator']=='PDF 第 23、24 页'
        assert provenance[0]['pages']==[23,24] and provenance[0]['excerpt']==rows[0]['text']
        assert tool.run(s,query='retriever',paper_ids=[])=='[]'
        all_hits=json.loads(tool.run(s,query='retriever'))
        assert {r['paper_id'] for r in all_hits}=={a.id,b.id}


def test_provider_failure_keeps_local_evidence_and_metadata_is_not_full_text(client,monkeypatch):
    from app.rag import scalable
    with Session(get_engine()) as s:
        paper=Paper(title='Metadata',source='manual');s.add(paper);s.commit()
        s.add(PaperChunk(paper_id=paper.id,ordinal=0,text='oracle evidence abstract',embedding=serialize([1,0]),embedding_model='fixture'));s.commit()
        monkeypatch.setattr(scalable,'hybrid',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError()))
        tool=get_tool('search_paper_text')
        raw=tool.run(s,query='oracle',paper_ids=[paper.id])
        row=json.loads(raw)[0]
        assert row['type']=='metadata' and row['retrieval_mode']=='keyword_fallback'
        assert tool_sources(s,'search_paper_text',raw)[0]['source_type']=='metadata'
        empty=tool.run(s,query='unfindable',paper_ids=[paper.id])
        assert 'note' in json.loads(empty)[0] and tool_sources(s,'search_paper_text',empty)==[]
