import time

import httpx
import pymupdf
from sqlmodel import Session

from app.config import get_settings
from app.db.engine import get_engine
from app.models import Paper
from app.providers.client import ProviderClient
from app.reading import advanced_parser, documents


def make_paper(pages=2):
    from pathlib import Path

    root = Path(get_settings().data_dir) / 'pdfs'
    root.mkdir(exist_ok=True, parents=True)
    path = root / 'fixture.pdf'
    with pymupdf.open() as pdf:
        for n in range(pages):
            page = pdf.new_page(width=400, height=500)
            page.insert_text((30, 40), f'Page {n + 1}: scanned garbage scan page.', fontsize=10)
            image = page.get_pixmap().tobytes('png')
            page.clean_contents()
            page.insert_image(page.rect, stream=image)
        pdf.save(path)
    with Session(get_engine()) as session:
        paper = Paper(title='Advanced parse fixture', source='pdf', pdf_path=path.name, full_text='Previous text')
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper.id


def finish(client, pid):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(f'/api/papers/{pid}/document').json()
        with documents._lock:
            active = (get_engine(), pid) in documents._active
        if state['status'] not in {'queued', 'running'} and state['index_status'] != 'pending' and not active:
            return state
        time.sleep(.02)
    raise AssertionError('job did not finish')


def set_url(client, url):
    assert client.put('/api/settings/advanced_parser_url', json={'value': url}).status_code == 200


def test_settings_reject_invalid_parser_url(client):
    assert client.put('/api/settings/advanced_parser_url', json={'value': 'not-a-url'}).status_code == 422
    set_url(client, 'http://127.0.0.1:9000 ')
    assert client.get('/api/settings/advanced_parser_url').json()['value'] == 'http://127.0.0.1:9000'
    assert client.put('/api/settings/advanced_parser_url', json={'value': ''}).status_code == 200


def test_advanced_mode_requires_configured_url(client):
    pid = make_paper()
    response = client.post(f'/api/papers/{pid}/document', json={'mode': 'advanced'})
    assert response.status_code == 422
    assert '高级解析引擎' in response.json()['detail']


def test_advanced_conversion_publishes_engine_pages(client, monkeypatch):
    pid = make_paper()
    set_url(client, 'http://127.0.0.1:9000')
    monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('engine mode must not call OCR')))
    monkeypatch.setattr(advanced_parser, 'parse_document',
                        lambda path, url, should_continue=None: {1: '引擎识别的第一页，含表格。', 2: 'Engine page two with table.'})
    assert client.post(f'/api/papers/{pid}/document', json={'mode': 'advanced'}).status_code == 200
    state = finish(client, pid)
    assert state['status'] == 'ready' and state['completed_pages'] == 2
    assert state['advanced_pages'] == 2 and state['ocr_pages'] == 0
    markdown = client.get(f'/api/papers/{pid}/document/markdown').json()['markdown']
    assert '引擎识别的第一页' in markdown and '<!-- page:2 -->' in markdown
    with Session(get_engine()) as session:
        assert session.get(Paper, pid).full_text == markdown


def test_advanced_engine_failure_keeps_original_text(client, monkeypatch):
    pid = make_paper()
    set_url(client, 'http://127.0.0.1:9000')

    def broken(path, url, should_continue=None):
        raise advanced_parser.AdvancedParseError('高级解析引擎报告失败。')

    monkeypatch.setattr(advanced_parser, 'parse_document', broken)
    client.post(f'/api/papers/{pid}/document', json={'mode': 'advanced'})
    state = finish(client, pid)
    assert state['status'] == 'error' and '高级解析引擎' in state['error']
    with Session(get_engine()) as session:
        assert session.get(Paper, pid).full_text == 'Previous text'


def test_advanced_page_count_mismatch_fails_clearly(client, monkeypatch):
    pid = make_paper(pages=2)
    set_url(client, 'http://127.0.0.1:9000')
    monkeypatch.setattr(advanced_parser, 'parse_document',
                        lambda path, url, should_continue=None: {1: 'only one page'})
    client.post(f'/api/papers/{pid}/document', json={'mode': 'advanced'})
    state = finish(client, pid)
    assert state['status'] == 'error' and '页数' in state['error']


def test_parse_document_protocol_polls_and_sanitizes(client, monkeypatch, tmp_path):
    polls = {'n': 0}

    def handler(request: httpx.Request):
        if request.url.path.endswith('/jobs') and request.method == 'POST':
            assert request.headers['content-type'].startswith('multipart/form-data')
            return httpx.Response(200, json={'job_id': 'j1'})
        polls['n'] += 1
        if polls['n'] == 1:
            return httpx.Response(200, json={'status': 'running'})
        return httpx.Response(200, json={'status': 'done', 'pages': [
            {'page': 1, 'markdown': 'hi'},
            {'page': 2, 'markdown': '<!-- page:9 --> y ![](x.png)'},
        ]})

    monkeypatch.setattr(advanced_parser, '_client', lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(advanced_parser, 'POLL_INTERVAL', 0)
    pdf = tmp_path / 'a.pdf'
    pdf.write_bytes(b'%PDF-1.4')
    result = advanced_parser.parse_document(pdf, 'http://127.0.0.1:9000')
    assert result == {1: 'hi', 2: '&lt;!-- page:9 --> y'}
    assert polls['n'] == 2

    monkeypatch.setattr(advanced_parser, '_client',
                        lambda: httpx.Client(transport=httpx.MockTransport(
                            lambda request: httpx.Response(200, json={'job_id': 'j2'} if request.method == 'POST' else {'status': 'running'}))))
    assert advanced_parser.parse_document(pdf, 'http://127.0.0.1:9000', should_continue=lambda: False) is None


def test_parse_document_rejects_duplicate_pages(client, monkeypatch, tmp_path):
    def handler(request: httpx.Request):
        if request.method == 'POST':
            return httpx.Response(200, json={'job_id': 'j9'})
        return httpx.Response(200, json={'status': 'done', 'pages': [
            {'page': 1, 'markdown': 'a'}, {'page': 1, 'markdown': 'b'}]})

    monkeypatch.setattr(advanced_parser, '_client', lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(advanced_parser, 'POLL_INTERVAL', 0)
    pdf = tmp_path / 'b.pdf'
    pdf.write_bytes(b'%PDF-1.4')
    try:
        advanced_parser.parse_document(pdf, 'http://127.0.0.1:9000')
        raise AssertionError('duplicate page must fail')
    except advanced_parser.AdvancedParseError as exc:
        assert '重复' in str(exc)
