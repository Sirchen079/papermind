import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import pytest
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Paper, PaperDocument, PaperChunk
from app.providers.client import ProviderClient
from app.reading import documents
from app.ingestion.service import persist_fetched
from app.ingestion.sources import FetchedPaper
from test_documents import make_paper, models, finish


def imported(client):
    # Generate a readable PDF; even its text pages must go through OCR.
    legacy, path = make_paper()
    with Session(get_engine()) as s:
        s.delete(s.get(Paper, legacy)); s.commit()
        return persist_fetched(s, FetchedPaper(source='pdf', source_ref='sample', title='New import', pdf_bytes=path.read_bytes()), path.parent).id


def test_default_import_waits_and_model_selection_starts_all_pages(client, monkeypatch):
    calls = []
    def complete(*a, **kw):
        calls.append(kw['request_kind'])
        return SimpleNamespace(content='## Results\n\n| Method | Score |\n|---|---|\n| New method | 40.32 |')
    monkeypatch.setattr(ProviderClient, 'complete', complete)
    monkeypatch.setattr(ProviderClient, 'embed', lambda *a, **kw: [[1.,0.]] * len(a[3]))
    pid = imported(client)
    state = client.get(f'/api/papers/{pid}/document').json()
    assert state['status'] == 'waiting_model' and state['mode'] == 'ocr'
    with Session(get_engine()) as s:
        p = s.get(Paper, pid)
        assert p.full_text is None
        from app.rag.index import index_paper, index_local_paper
        assert index_local_paper(s, p) == 0 and index_paper(s, p) == 0
    assert not calls
    models(client)
    state = finish(client, pid)
    assert state['status'] == 'ready' and state['ocr_pages'] == state['total_pages'] == 2
    assert state['index_status'] == 'ready'
    assert calls == ['pdf_ocr','pdf_ocr']
    with Session(get_engine()) as s:
        row = s.get(PaperDocument,pid)
        assert json.loads(row.followup_json)['finished']
        assert s.get(Paper,pid).full_text == row.markdown
        assert all(c.embedding for c in s.exec(select(PaperChunk).where(PaperChunk.paper_id==pid)))


def test_unfinished_import_resumes_without_charging_completed_page(client, monkeypatch):
    models(client)
    calls=[]
    def complete(*a,**kw):
        calls.append(1)
        if len(calls)==2:
            raise RuntimeError('not public')
        return SimpleNamespace(content='Faithfully recognized text')
    monkeypatch.setattr(ProviderClient,'complete',complete)
    monkeypatch.setattr(ProviderClient,'embed',lambda *a,**kw:[[1.,0.]] * len(a[3]))
    pid=imported(client)
    assert finish(client,pid)['status']=='error'
    with Session(get_engine()) as s:
        row=s.get(PaperDocument,pid)
        row.status='running';s.add(row);s.commit()
    from app.ingestion.document_pipeline import resume_imports
    resume_imports(get_engine())
    assert finish(client,pid)['status']=='ready'
    assert len(calls)==3


def test_ocr_publish_clears_changed_vectors_when_embedding_fails(client, monkeypatch):
    models(client)
    pid,_=make_paper()
    with Session(get_engine()) as s:
        s.add(PaperChunk(paper_id=pid,ordinal=0,text='Old native body',embedding=b'old',embedding_model='vector'))
        s.commit()
    monkeypatch.setattr(ProviderClient,'complete',lambda *a,**kw:SimpleNamespace(content='New OCR evidence'))
    monkeypatch.setattr(ProviderClient,'embed',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('offline')))
    client.post(f'/api/papers/{pid}/document',json={'mode':'ocr'})
    state=finish(client,pid)
    assert state['status']=='ready' and state['index_status']=='error'
    with Session(get_engine()) as s:
        chunks=s.exec(select(PaperChunk).where(PaperChunk.paper_id==pid)).all()
        assert any('New OCR evidence' in c.text for c in chunks)
        assert all(c.embedding is None for c in chunks)
        assert not any('Old native body' in c.text for c in chunks)


def test_existing_library_duplicate_keeps_its_text_without_new_ocr(client,monkeypatch):
    pid,path=make_paper()
    monkeypatch.setattr(ProviderClient,'complete',lambda *a,**kw:pytest.fail('legacy duplicate must not trigger OCR'))
    with Session(get_engine()) as s:
        p=persist_fetched(s,FetchedPaper(source='pdf',source_ref='renamed',title='Renamed',pdf_bytes=path.read_bytes()),path.parent)
        assert p.id==pid and p.full_text=='Previous text'
        assert s.get(PaperDocument,pid) is None


def test_html_table_grounding_and_long_chunks_keep_header_group_labels():
    from app.reading.ocr_markdown import normalize
    from app.rag.markdown_chunker import chunk_markdown
    raw='<|ref|>table<|/ref|><|det|>[[1,2,3,4]]<|/det|>\n<table><tr><td>Model</td><td>Method</td><td>Score</td></tr><tr><td rowspan="3">A</td><td>Base</td><td>2</td></tr><tr><td>New</td><td>3</td></tr><tr><td rowspan="2">B</td><td>Base</td><td>4</td></tr><tr><td>New</td><td>5</td></tr></table>'
    text=normalize(raw)
    assert '<|ref|>' not in text and '<table' not in text
    assert '| A | New | 3 |' in text and '| B | Base | 4 |' in text and '| B | New | 5 |' in text
    chunks=chunk_markdown('Table 1. Accuracy (%)\n\n'+text,target=110)
    assert len(chunks)>1
    for c in chunks:
        if '| Base |' in c or '| New |' in c:
            assert 'Model | Method | Score' in c and 'Accuracy (%)' in c
    assert sum(c.count('| New |') for c in chunks)==2


def test_deepseek_ocr_image_precedes_official_prompt_and_fits_context():
    def complete(provider,model,messages,**kw):
        assert messages[0]['content'][0]['type']=='image_url'
        assert '<|grounding|>' in messages[0]['content'][1]['text']
        assert kw['max_tokens']<8192
        return SimpleNamespace(content='Actual recognized document text')
    ctx=(SimpleNamespace(complete=complete),object(),'deepseek-ai/DeepSeek-OCR')
    assert documents.transcribe(ctx,b'png',1)=='Actual recognized document text'


def test_dedicated_ocr_does_not_become_fallback_chat_but_explicit_shared_chat_works(client):
    from app.models import Model
    from app.providers.selection import pick_llm
    ids=models(client)
    with Session(get_engine()) as s:
        chat=s.get(Model,ids['chat']);chat.role_default=None;s.delete(chat);s.commit()
        # Unassigned OCR is excluded from implicit text fallback.
        ctx=pick_llm(s,'chat')
        assert ctx is None or ctx[2]!='vision'
        vision=s.get(Model,ids['vision']);vision.role_default='chat';s.add(vision);s.commit()
        assert pick_llm(s,'chat')[2]=='vision'


def test_delayed_import_does_not_analyze_with_newly_selected_ocr_only_model(client,monkeypatch):
    from app.models import Model
    ids=models(client)
    with Session(get_engine()) as s:
        paper=Paper(source='pdf',title='Converted import',full_text='<!-- page:1 -->\nOriginal OCR evidence')
        s.add(paper);s.commit();s.refresh(paper)
        vision=s.get(Model,ids['vision'])
        s.add(PaperDocument(paper_id=paper.id,status='running',markdown=paper.full_text,followup_json=json.dumps({'ingest':True,'analysis':{'provider_id':vision.provider_id,'model_id':vision.model_id}})))
        s.commit()
        monkeypatch.setattr('app.ingestion.service._analyze',lambda *a,**kw:pytest.fail('OCR-only connection must not run text analysis'))
        from app.ingestion.document_pipeline import finish_import
        finish_import(s,paper.id)
        assert json.loads(s.get(PaperDocument,paper.id).followup_json)['finished']


def test_deferred_analysis_observes_published_markdown_and_runs_once(client,monkeypatch):
    from app.models import Model
    ids=models(client)
    seen=[]
    monkeypatch.setattr('app.ingestion.service._analyze',lambda session,p,*a,**kw:seen.append((p.full_text,kw['index'])))
    with Session(get_engine()) as s:
        p=Paper(source='pdf',title='Delayed analysis',full_text='<!-- page:1 -->\nPublished Markdown')
        s.add(p);s.commit();s.refresh(p)
        model=s.get(Model,ids['chat'])
        s.add(PaperDocument(paper_id=p.id,markdown=p.full_text,followup_json=json.dumps({'ingest':True,'analysis':{'provider_id':model.provider_id,'model_id':model.model_id}})))
        s.commit()
        from app.ingestion.document_pipeline import finish_import
        finish_import(s,p.id);finish_import(s,p.id)
        assert seen==[(p.full_text,False)]


def test_markdown_section_navigation_keeps_page_provenance_and_ignores_page_titles():
    from app.agent.paper_navigation import paper_sections
    text='<!-- page:1 -->\n## 第 1 页\n\n# Introduction\n\nText\n<!-- page:2 -->\n## 第 2 页\n\n## 2 Methods\n\nEvidence'
    headings=paper_sections(text)
    assert [r['title'] for r in headings]==['Introduction','Methods']
    assert headings[0]['pages']==[1] and headings[1]['pages']==[2]
