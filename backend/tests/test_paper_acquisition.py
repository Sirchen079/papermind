import json
from pathlib import Path
from threading import Event
from unittest.mock import patch

import httpx
import pymupdf
import pytest
from sqlmodel import Session, select

from app.agent.paper_acquisition import import_paper_pdf
from app.agent.tools import get_tool
from app.agent.provenance import tool_sources
from app.config import get_settings
from app.db.engine import get_engine
from app.ingestion.pdf_download import download_pdf
from app.models import Paper, PaperChunk
from app.providers.client import ToolCall
from test_chat_api import _seed_chat_provider, _turn


def pdf(text='GSOT evidence from the experiment.', large=False):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), text)
        doc.new_page().insert_text((72, 72), 'Amplitude normalization with paired noise realizations.')
        raw = doc.tobytes()
    if large:
        # Valid PDF with an uncompressed comment before xref and an adjusted
        # startxref, exercising actual >10 MB transport and parsing.
        marker = raw.index(b'xref\n')
        padding = b'%' + b'x' * (11 * 1024 * 1024) + b'\n'
        old_start = raw.rsplit(b'startxref\n', 1)[1].splitlines()[0]
        raw = raw[:marker] + padding + raw[marker:]
        raw = raw.replace(b'startxref\n' + old_start + b'\n', b'startxref\n' + str(int(old_start) + len(padding)).encode() + b'\n')
    return raw


def network(monkeypatch, handler):
    def offline_metadata(doi):
        raise RuntimeError('offline test')
    monkeypatch.setattr('app.ingestion.sources.fetch_crossref', offline_metadata)
    real = httpx.Client
    requests = []
    def route(request):
        requests.append(str(request.url))
        return handler(request)
    transport = httpx.MockTransport(route)
    monkeypatch.setattr('app.ingestion.pdf_download.httpx.Client', lambda **kwargs: real(transport=transport, **kwargs))
    return requests


def test_large_pdf_attaches_to_curated_paper_and_is_readable_offline(client, monkeypatch):
    # This case exercises the explicitly selected native extraction mode.
    client.put('/api/settings/pdf_ingest_mode', json={'value': 'manual'}).raise_for_status()
    raw = pdf(large=True)
    assert len(raw) > 10 * 1024 * 1024
    requests = network(monkeypatch, lambda request: httpx.Response(200, content=raw, headers={'content-type': 'application/pdf'}))
    with Session(get_engine()) as session:
        paper = Paper(source='bibtex', title='Curated GSOT title', doi='10.1000/original', authors_json='["Ada"]', source_ref='original-bibtex')
        session.add(paper); session.commit(); pid = paper.id
        first = json.loads(import_paper_pdf(session, 'https://archive.example/paper.pdf', paper_id=pid, title='Wrong filename', doi='wrong'))
        stored = session.get(Paper, pid)
        assert stored.title == 'Curated GSOT title' and stored.doi == '10.1000/original'
        assert stored.authors_json == '["Ada"]' and stored.source_ref == 'original-bibtex'
        assert len(session.exec(select(Paper)).all()) == 1
        assert first['pages'] == 2 and first['download']['bytes'] == len(raw)
        assert first['indexing']['local_chunks'] >= 3 and first['indexing']['status'] == 'local_only'
        assert Path(stored.pdf_path).read_bytes() == raw
        receipt = json.loads(Path(stored.pdf_path).with_suffix('.source.json').read_text())
        assert receipt == first['download']
        assert tool_sources(session, 'import_paper_pdf', json.dumps(first)) == []  # import is not a read
        read = get_tool('get_paper_full_text').run(session, paper_id=pid, page=2)
        assert 'Amplitude normalization' in read
        assert tool_sources(session, 'get_paper_full_text', read)[0]['pages'] == [2]
        found = json.loads(get_tool('search_paper_text').run(session, query='paired noise', paper_ids=[pid]))
        assert found[0]['pages'][0] == 2  # adjacent-page context is retained too
        again = json.loads(import_paper_pdf(session, 'https://archive.example/paper.pdf', paper_id=pid))
        assert again['status'] == 'already_available' and len(requests) == 1
    assert list((get_settings().data_dir / 'downloads').iterdir()) == []


def test_acquired_file_link_stays_in_current_project(client, monkeypatch):
    from app.workspaces.context import WorkspaceContext, bind_workspace
    network(monkeypatch, lambda request: httpx.Response(200, content=pdf()))
    settings = get_settings()
    scope = WorkspaceContext(id='research-2', data_dir=settings.data_dir,
        db_path=settings.resolved_db_path, master_key_path=settings.resolved_master_key_path)
    with bind_workspace(scope), Session(get_engine()) as session:
        result = json.loads(import_paper_pdf(session, 'https://archive.example/paper.pdf', title='Project paper'))
        assert result['file_url'] == f'/api/w/research-2/papers/{result["paper_id"]}/file'


@pytest.mark.parametrize('bad', [b'<html>login required</html>' * 100, b'%PDF-1.7\nnot a complete document'])
def test_invalid_response_keeps_existing_material_and_cleans_temp(client, monkeypatch, bad):
    network(monkeypatch, lambda request: httpx.Response(200, content=bad, headers={'content-type': 'application/pdf'}))
    with Session(get_engine()) as session:
        paper = Paper(source='manual', title='Existing', full_text='Prior manual extraction')
        session.add(paper); session.commit(); pid = paper.id
        with pytest.raises(ValueError):
            import_paper_pdf(session, 'https://archive.example/paper.pdf', paper_id=pid)
        assert session.get(Paper, pid).full_text == 'Prior manual extraction'
        assert session.get(Paper, pid).pdf_path is None
    assert list((get_settings().data_dir / 'downloads').iterdir()) == []


def test_interrupted_stream_and_cancel_never_import_partial_pdf(client, monkeypatch):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b'%PDF-1.7\n' + b'a' * 66000
            raise httpx.ReadError('interrupted')
    network(monkeypatch, lambda request: httpx.Response(200, stream=Broken()))
    with Session(get_engine()) as session:
        with pytest.raises(httpx.ReadError):
            import_paper_pdf(session, 'https://archive.example/paper.pdf', title='A paper')
        assert session.exec(select(Paper)).all() == []
    assert list((get_settings().data_dir / 'downloads').iterdir()) == []


def test_cancel_download_cleans_file_and_redirects_are_validated(client, monkeypatch):
    stop = Event()
    class Stopping(httpx.SyncByteStream):
        def __iter__(self):
            yield b'%PDF-1.7\n' + b'a' * 66000
            stop.set()
            yield b'a' * 66000
    requests = network(monkeypatch, lambda request: httpx.Response(200, stream=Stopping()))
    with pytest.raises(InterruptedError):
        with download_pdf('https://archive.example/paper.pdf', get_settings().data_dir, stop):
            pytest.fail('cancelled transfer must not yield a file')
    assert len(requests) == 1
    assert list((get_settings().data_dir / 'downloads').iterdir()) == []


@pytest.mark.parametrize('location', ['file:///private.pdf', '/actual.pdf'])
def test_download_redirect_behavior(client, monkeypatch, location):
    raw = pdf()
    def handler(request):
        return httpx.Response(200, content=raw) if request.url.path == '/actual.pdf' else httpx.Response(302, headers={'location': location})
    requests = network(monkeypatch, handler)
    if location.startswith('file:'):
        with pytest.raises(ValueError):
            with download_pdf('https://archive.example/start', get_settings().data_dir):
                pytest.fail('non-HTTP redirect')
        assert len(requests) == 1
    else:
        with download_pdf('https://archive.example/start', get_settings().data_dir) as (path, receipt):
            assert path.read_bytes() == raw
            assert receipt['url'] == 'https://archive.example/actual.pdf'
        assert not path.exists()


def test_embedding_failure_leaves_new_text_locally_searchable(client, monkeypatch):
    client.put('/api/settings/pdf_ingest_mode', json={'value': 'manual'}).raise_for_status()
    from app.rag.index import index_local_paper
    raw = pdf()
    network(monkeypatch, lambda request: httpx.Response(200, content=raw))
    monkeypatch.setattr('app.rag.index.index_paper', lambda *args: (_ for _ in ()).throw(TimeoutError('embedding down')))
    with Session(get_engine()) as session:
        result = json.loads(import_paper_pdf(session, 'https://archive.example/paper.pdf', title='New GSOT', doi='10.1000/test'))
        assert result['indexing']['status'] == 'local_only'
        assert result['indexing']['error_type'] == 'TimeoutError'
        paper = session.get(Paper, result['paper_id'])
        chunks = session.exec(select(PaperChunk).where(PaperChunk.paper_id == paper.id)).all()
        assert any('paired noise' in c.text for c in chunks)
        chunks[0].embedding = b'vector'; chunks[0].embedding_model = 'test'
        session.add(chunks[0]); session.commit()
        index_local_paper(session, paper)
        assert session.get(PaperChunk, chunks[0].id).embedding == b'vector'
        paper.title = 'Changed metadata'; session.add(paper); session.commit()
        index_local_paper(session, paper)
        assert session.get(PaperChunk, chunks[0].id).embedding is None


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_agent_import_read_and_retry_keep_one_paper_and_page_sources(client, monkeypatch, suffix):
    client.put('/api/settings/pdf_ingest_mode', json={'value': 'manual'}).raise_for_status()
    _seed_chat_provider()
    requests = network(monkeypatch, lambda request: httpx.Response(200, content=pdf()))
    cid = client.post('/api/chat/conversations').json()['id']
    calls = [_turn('', [ToolCall('import', 'import_paper_pdf', {'url': 'https://archive.example/paper.pdf', 'title': 'Identified paper'})]),
             TimeoutError('model interrupted'),
             _turn('', [ToolCall('read', 'get_paper_full_text', {'paper_id': 1, 'page': 2})]),
             _turn('The experiment uses paired noise [P1].')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=calls):
        client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Read the known public paper'})
        first = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
        assert first['continuable'] and len(first['tools']) == 1
        receipt = json.loads(first['tools'][0]['result'])
        assert receipt['ok'] and receipt['download']['sha256']
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': first['content'], 'retry_message_id': first['id']})
    assert response.status_code == 200 and len(requests) == 1
    last = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert last['sources'][0]['pages'] == [2]
    assert last['sources'][0]['retrieved_by'] == 'get_paper_full_text'
    assert len(client.get('/api/papers').json()['items']) == 1

def test_arxiv_direct_pdf_metadata_and_retry_receipt(client, monkeypatch):
    from app.ingestion.sources import FetchedPaper
    requests = network(monkeypatch, lambda request: httpx.Response(200, content=pdf()))
    lookups = []
    def metadata(identifier, client=None, download_pdf=True):
        lookups.append(identifier)
        assert not download_pdf and client._session.get.keywords['timeout'] == 15
        return FetchedPaper(source='arxiv', title='Publisher title', authors=['Verified Author'],
                            abstract='Verified abstract', year=2025, arxiv_id=identifier)
    monkeypatch.setattr('app.ingestion.sources.fetch_arxiv', metadata)
    with Session(get_engine()) as s:
        first = json.loads(import_paper_pdf(s, 'https://arxiv.org/pdf/2508.17122v1', title='Curated title', doi='10.48550/arXiv.2508.17122'))
        p = s.get(Paper, first['paper_id'])
        assert json.loads(p.authors_json) == ['Verified Author'] and p.year == 2025
        assert p.arxiv_id == '2508.17122v1' and p.abstract == 'Verified abstract'
        assert p.title == 'Curated title' and p.doi == '10.48550/arXiv.2508.17122'
        again = json.loads(import_paper_pdf(s, 'https://arxiv.org/pdf/2508.17122v1', title='Curated title'))
        assert again['status'] == 'already_available' and again['metadata'] == first['metadata']
        assert first['metadata']['status'] == 'retrieved'
        assert len(requests) == len(lookups) == 1
        assert len(s.exec(select(Paper)).all()) == 1


def test_arxiv_metadata_outage_retains_readable_pdf(client, monkeypatch):
    client.put('/api/settings/pdf_ingest_mode', json={'value': 'manual'}).raise_for_status()
    network(monkeypatch, lambda request: httpx.Response(200, content=pdf()))
    monkeypatch.setattr('app.ingestion.sources.fetch_arxiv', lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    with Session(get_engine()) as s:
        result = json.loads(import_paper_pdf(s, 'https://arxiv.org/pdf/2508.17122v1', title='Available paper'))
        assert result['ok'] and result['metadata']['status'] == 'unavailable'
        assert result['metadata']['error_type'] == 'TimeoutError'
        assert result['pages'] == 2 and result['indexing']['local_chunks'] > 0
        assert 'paired noise' in s.get(Paper, result['paper_id']).full_text


def test_existing_arxiv_paper_keeps_curated_metadata(client, monkeypatch):
    network(monkeypatch, lambda request: httpx.Response(200, content=pdf()))
    monkeypatch.setattr('app.ingestion.sources.fetch_arxiv', lambda *a, **k: pytest.fail('curated record lookup'))
    with Session(get_engine()) as s:
        p=Paper(source='manual',title='My title',authors_json='["My author"]',year=2020)
        s.add(p);s.commit()
        result=json.loads(import_paper_pdf(s,'https://arxiv.org/pdf/2508.17122v1',paper_id=p.id))
        assert result['ok'] and p.title=='My title' and p.year==2020 and p.authors_json=='["My author"]'

def test_arxiv_url_matches_curated_record_before_metadata_lookup(client, monkeypatch):
    network(monkeypatch, lambda request: httpx.Response(200, content=pdf()))
    monkeypatch.setattr('app.ingestion.sources.fetch_arxiv', lambda *a, **k: pytest.fail('existing arxiv record lookup'))
    with Session(get_engine()) as s:
        p = Paper(source='manual', title='Curated display title', arxiv_id='2508.17122v1',
                  authors_json='["Curated author"]', year=2026)
        s.add(p); s.commit(); pid = p.id
        result = json.loads(import_paper_pdf(s, 'https://arxiv.org/pdf/2508.17122v1', title='New alternative title'))
        assert result['paper_id'] == pid and len(s.exec(select(Paper)).all()) == 1
        assert p.title == 'Curated display title' and p.year == 2026
        assert p.authors_json == '["Curated author"]'


def test_default_pdf_import_waits_for_ocr_before_exposing_read_evidence(client, monkeypatch):
    network(monkeypatch, lambda request: httpx.Response(200, content=pdf()))
    with Session(get_engine()) as session:
        result = json.loads(import_paper_pdf(session, 'https://archive.example/paper.pdf', title='Waiting for OCR'))
        pid = result['paper_id']
        assert result['ok'] and result['document']['status'] == 'waiting_model'
        assert result['indexing']['status'] == 'waiting_markdown'
        assert result['full_text_chars'] == 0
        assert session.get(Paper, pid).full_text is None
        assert session.exec(select(PaperChunk).where(PaperChunk.paper_id == pid)).all() == []
        read = get_tool('get_paper_full_text').run(session, paper_id=pid, page=1)
        assert 'waiting_model' in read and 'GSOT' not in read
        assert tool_sources(session, 'get_paper_full_text', read) == []
