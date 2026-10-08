"""Resource discovery must survive OCR omission without pretending to read a site."""
import hashlib
import json

import pymupdf
from sqlmodel import Session, SQLModel

from app.agent.provenance import tool_sources
from app.agent.tools import get_tool, t_get_paper_links
from app.db.engine import make_engine
from app.models import Paper


def seed(env, *, blank=False):
    path = env / 'data' / 'pdfs' / 'resources.pdf'
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        page = doc.new_page()
        if not blank:
            page.insert_text((50, 60), 'Code and trained models: https://example.org/project')
            # Target differs from the displayed URL; preserve the annotation URI.
            page.insert_link({'kind': pymupdf.LINK_URI, 'from': pymupdf.Rect(50, 48, 390, 64),
                              'uri': 'https://example.org/resources'})
            page.insert_link({'kind': pymupdf.LINK_URI, 'from': pymupdf.Rect(50, 48, 390, 64),
                              'uri': 'https://example.org/resources'})
            page.insert_text((50, 110), 'Dataset: https://example.org/data.')
            page.insert_link({'kind': pymupdf.LINK_URI, 'from': pymupdf.Rect(50, 160, 390, 180),
                              'uri': 'javascript:alert(1)'})
            page.insert_link({'kind': pymupdf.LINK_URI, 'from': pymupdf.Rect(50, 180, 390, 200),
                              'uri': 'file:///C:/private.txt'})
            second = doc.new_page()
            second.insert_text((50, 60), 'Appendix: https://example.org/resources')
        else:
            page.insert_link({'kind': pymupdf.LINK_URI, 'from': pymupdf.Rect(50, 48, 390, 64),
                              'uri': 'https://example.org/resources'})
        doc.save(path)
    engine = make_engine(':memory:')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        paper = Paper(source='manual', title='Resource paper', pdf_path=path.name,
                      full_text='<!-- page:1 -->\nOCR omitted every resource footnote.')
        session.add(paper)
        session.commit()
        return engine, paper.id, path


def test_original_links_survive_ocr_omission_and_keep_pdf_provenance(env):
    engine, pid, path = seed(env)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with Session(engine) as session:
        raw = t_get_paper_links(session, pid)
        result = json.loads(raw)
        assert [(link['page'], link['url']) for link in result['links']] == [
            (1, 'https://example.org/resources'), (1, 'https://example.org/project'),
            (1, 'https://example.org/data'), (2, 'https://example.org/resources')]
        assert result['links'][0]['extraction'] == 'pdf_annotation'
        assert 'trained models' in result['links'][0]['context']
        assert result['links'][2]['extraction'] == 'printed_url'
        sources = tool_sources(session, 'get_paper_links', raw)
        assert len(sources) == 4
        assert all(source['material_kind'] == 'original_text' and source['source_type'] == 'full_text'
                   and 'snapshot_id' not in source for source in sources)
        assert sources[0]['pages'] == [1] and sources[-1]['pages'] == [2]
        assert session.get(Paper, pid).full_text.endswith('OCR omitted every resource footnote.')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_link_pagination_page_scope_and_schema(env):
    engine, pid, _ = seed(env)
    assert get_tool('get_paper_links').parameters['required'] == ['paper_id']
    with Session(engine) as session:
        first = json.loads(t_get_paper_links(session, pid, page=1, limit=2))
        second = json.loads(t_get_paper_links(session, pid, page=1, offset=first['next_offset'], limit=2))
        assert first['total_links'] == second['total_links'] == 3
        assert first['next_offset'] == 2 and second['next_offset'] is None
        assert len(first['links'] + second['links']) == 3
        assert all(link['page'] == 1 for link in first['links'] + second['links'])
        assert json.loads(t_get_paper_links(session, pid, offset=10000))['links'] == []


def test_annotation_without_pdf_text_never_becomes_website_evidence(env):
    engine, pid, _ = seed(env, blank=True)
    with Session(engine) as session:
        raw = t_get_paper_links(session, pid)
        assert json.loads(raw)['links'][0]['context'] == ''
        assert tool_sources(session, 'get_paper_links', raw) == []


def test_unavailable_deleted_outside_encrypted_and_invalid_files(env):
    engine, pid, path = seed(env)
    with Session(engine) as session:
        for page in (0, True, 3):
            raw = t_get_paper_links(session, pid, page=page)
            assert 'error' in json.loads(raw) and tool_sources(session, 'get_paper_links', raw) == []
        paper = session.get(Paper, pid)
        paper.is_deleted = True
        assert 'error' in json.loads(t_get_paper_links(session, pid))
        paper.is_deleted = False
        outside = env / 'outside.pdf'
        outside.write_bytes(path.read_bytes())
        paper.pdf_path = str(outside)
        assert 'error' in json.loads(t_get_paper_links(session, pid))
        paper.pdf_path = path.name
        with pymupdf.open() as doc:
            doc.new_page()
            encrypted = path.with_name('encrypted.pdf')
            doc.save(encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                     owner_pw='owner', user_pw='reader')
        paper.pdf_path = encrypted.name
        assert 'error' in json.loads(t_get_paper_links(session, pid))
        paper.pdf_path = path.name
        path.write_bytes(b'not a PDF')
        assert 'error' in json.loads(t_get_paper_links(session, pid))
        path.unlink()
        assert 'error' in json.loads(t_get_paper_links(session, pid))
        assert 'error' in json.loads(t_get_paper_links(session, 999999))


def test_empty_scan_is_inconclusive(env):
    engine, pid, path = seed(env, blank=True)
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path)
    with Session(engine) as session:
        raw = t_get_paper_links(session, pid)
        result = json.loads(raw)
        assert result['links'] == [] and result['total_links'] == 0
        assert 'does not prove' in result['note']
        assert tool_sources(session, 'get_paper_links', raw) == []
