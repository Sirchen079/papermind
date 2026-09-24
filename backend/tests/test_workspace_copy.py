from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Paper, PaperNote, PaperExcerpt, Summary, ReviewMatrixEntry, WorkspaceCopy
from app.workspaces.context import bind_workspace


def setup(client):
    ids=[]
    for name in ('Copy source', 'Copy destination'):
        response=client.post('/api/workspaces',json={'name':name})
        assert response.status_code==201,response.text
        ids.append(response.json()['id'])
    origin=client.app.state.workspaces.context(ids[0])
    target=client.app.state.workspaces.context(ids[1])
    pdf=origin.data_dir/'pdfs'/'original.pdf'
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b'%PDF-1.4\nSynthetic original evidence\n%%EOF')
    with bind_workspace(origin),Session(get_engine()) as session:
        paper=Paper(source='pdf',source_ref=str(pdf),title='Reusable evidence',title_norm='reusable evidence',doi='10.1234/test',citation_key='Shared2026',pdf_path=str(pdf),full_text='Full text evidence')
        session.add(paper);session.flush()
        session.add(PaperNote(paper_id=paper.id,content='Interpretation in source'))
        session.add(PaperExcerpt(paper_id=paper.id,quote='Original excerpt',page=1))
        session.add(Summary(paper_id=paper.id,content_json='{"freeform":"Project-specific summary"}'))
        session.add(ReviewMatrixEntry(paper_id=paper.id,relation_to_thesis='Only source thesis'))
        session.commit()
    return origin,target,pdf


def test_copy_pdf_and_optional_notes_is_independent_and_has_provenance(client):
    origin,target,pdf=setup(client)
    body={'target_workspace':target.id,'request_id':uuid4().hex,'include_notes':True}
    path=f'/api/w/{origin.id}/papers/1/copy-to-workspace'
    response=client.post(path,json=body)
    assert response.status_code==201,response.text
    copied_id=response.json()['paper_id']
    assert client.post(path,json=body).json()['reused'] is True

    with bind_workspace(target),Session(get_engine()) as session:
        copied=session.get(Paper,copied_id)
        target_file=target.data_dir/'pdfs'/copied.pdf_path
        assert target_file.read_bytes()==pdf.read_bytes()
        assert target_file.resolve()!=pdf.resolve()
        assert copied.source_ref is None
        assert copied.full_text=='Full text evidence'
        assert len(session.exec(select(PaperNote)).all())==1
        assert len(session.exec(select(PaperExcerpt)).all())==1
        assert session.exec(select(Summary)).all()==[]
        assert session.exec(select(ReviewMatrixEntry)).all()==[]
    assert client.delete(f'/api/w/{origin.id}/papers/1').status_code==204
    pdf.write_bytes(b'Original changed after copy')
    detail=client.get(f'/api/w/{target.id}/papers/{copied_id}').json()
    assert detail['title']=='Reusable evidence'
    assert detail['copied_from']['source_name']=='Copy source'
    assert client.get(f'/api/w/{target.id}/papers/{copied_id}/file').content.startswith(b'%PDF-1.4')
    # A completed receipt can be retried even after the source is removed.
    assert client.post(path,json=body).json()['reused'] is True


def test_parallel_retries_make_one_copy_and_no_notes_by_default(client):
    origin,target,_=setup(client)
    body={'target_workspace':target.id,'request_id':uuid4().hex}
    path=f'/api/w/{origin.id}/papers/1/copy-to-workspace'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post(path,json=body),range(2)))
    assert [r.status_code for r in results]==[201,201]
    assert sorted(r.json()['reused'] for r in results)==[False,True]
    with bind_workspace(target),Session(get_engine()) as session:
        assert len(session.exec(select(Paper)).all())==1
        assert len(session.exec(select(WorkspaceCopy)).all())==1
        assert session.exec(select(PaperNote)).all()==[]
    assert len(list((target.data_dir/'pdfs').glob('*.pdf')))==1
    assert client.post(path,json={**body,'include_notes':True}).status_code==409
    assert client.post(path,json={**body,'request_id':uuid4().hex}).status_code==409
    assert client.delete(f'/api/w/{target.id}/papers/1').status_code==204
    assert client.post(path,json=body).status_code==409
    assert client.post(path,json={**body,'request_id':uuid4().hex}).status_code==201


def test_invalid_target_missing_pdf_and_write_failure_leave_no_half_copy(client,monkeypatch):
    origin,target,pdf=setup(client)
    path=f'/api/w/{origin.id}/papers/1/copy-to-workspace'
    body={'target_workspace':target.id,'request_id':uuid4().hex}
    assert client.post(path,json={**body,'target_workspace':origin.id}).status_code==409
    assert client.post(path,json={**body,'target_workspace':'0'*32}).status_code==404
    assert client.post(path,json={**body,'target_workspace':'../legacy'}).status_code==422
    client.patch('/api/workspaces/'+target.id,json={'archived':True})
    assert client.post(path,json=body).status_code==409
    client.patch('/api/workspaces/'+target.id,json={'archived':False})
    pdf.rename(pdf.with_suffix('.offline'))
    assert client.post(path,json=body).status_code==409
    pdf.with_suffix('.offline').rename(pdf)
    original_commit=Session.commit
    def fail_commit(session):
        if str(session.get_bind().url.database)==str(target.db_path):
            raise OSError('Synthetic full disk at commit')
        original_commit(session)
    with monkeypatch.context() as patch:
        patch.setattr(Session,'commit',fail_commit)
        assert client.post(path,json=body).status_code==503
    with bind_workspace(target),Session(get_engine()) as session:
        assert session.exec(select(Paper)).all()==[]
        assert session.exec(select(WorkspaceCopy)).all()==[]
    assert list((target.data_dir/'pdfs').glob('*.pdf'))==[]
    assert client.post(path,json=body).status_code==201


def test_copy_keeps_published_markdown_and_images_without_model_ids(client):
    import hashlib
    from app.models import PaperDocument
    from app.reading.documents import artifact_dir
    origin, target, pdf = setup(client)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    markdown = '# Converted\n\n<!-- page:1 -->\nTable text\n[Original](page-1.png)'
    root = artifact_dir(origin.data_dir / 'pdfs', 1, sha)
    root.mkdir(parents=True)
    (root / 'page-1.png').write_bytes(b'image fixture')
    with bind_workspace(origin), Session(get_engine()) as session:
        session.add(PaperDocument(paper_id=1, source_hash=sha, published_hash=sha, markdown=markdown,
            status='ready', model_config_id=99, model_name='Origin vision', total_pages=1,
            pages_json='[{"page":1,"method":"ocr","markdown":"Table text"}]'))
        paper = session.get(Paper, 1); paper.full_text = markdown
        session.add(paper); session.commit()
    response = client.post(f'/api/w/{origin.id}/papers/1/copy-to-workspace', json={'target_workspace':target.id,'request_id':uuid4().hex})
    assert response.status_code == 201
    pid = response.json()['paper_id']
    with bind_workspace(target), Session(get_engine()) as session:
        doc = session.get(PaperDocument, pid)
        assert doc.markdown == markdown and doc.model_config_id is None
        assert session.get(Paper, pid).full_text == markdown
        copied = artifact_dir(target.data_dir / 'pdfs', pid, sha) / 'page-1.png'
        assert copied.read_bytes() == b'image fixture' and copied != root / 'page-1.png'
