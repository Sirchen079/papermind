import io
import json
import time
import zipfile
from threading import Event
from types import SimpleNamespace

import pymupdf
import pytest
from sqlmodel import Session, select
from app.config import get_settings
from app.db.engine import get_engine
from app.models import Paper, PaperDocument, PaperChunk, Setting
from app.providers.client import ProviderClient
from app.reading import documents


def make_paper(pages=2, scan=False):
    from pathlib import Path
    root = Path(get_settings().data_dir) / 'pdfs'
    root.mkdir(exist_ok=True, parents=True)
    path = root / 'fixture.pdf'
    with pymupdf.open() as pdf:
        for n in range(pages):
            page = pdf.new_page(width=400, height=500)
            page.insert_text((30, 40), f'Page {n + 1}: original scientific document with table and formula.', fontsize=10)
            if scan:
                image = page.get_pixmap().tobytes('png')
                page.clean_contents()
                page.insert_image(page.rect, stream=image)
        pdf.save(path)
    with Session(get_engine()) as session:
        paper = Paper(title='OCR fixture', source='pdf', pdf_path=path.name, full_text='Previous text')
        session.add(paper); session.commit(); session.refresh(paper)
        return paper.id, path


def models(client):
    provider = client.post('/api/providers', json={'name': 'Test', 'type': 'openai_compat', 'base_url': 'https://example.test/v1'}).json()['id']
    ids = {}
    for name, role in [('vision', None), ('ranker', None), ('chat', 'chat'), ('vector', 'embedding')]:
        ids[name] = client.post(f'/api/providers/{provider}/models', json={'model_id': name, 'role_default': role}).json()['id']
    assert client.put('/api/settings/ocr_model_config_id', json={'value': str(ids['vision'])}).status_code == 200
    return ids


def finish(client, pid):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(f'/api/papers/{pid}/document').json()
        with documents._lock:
            active = (get_engine(), pid) in documents._active
        if state['status'] not in {'queued', 'running'} and not active:
            return state
        time.sleep(.02)
    raise AssertionError('job did not finish')


def test_native_conversion_cached_and_portable_bundle(client, monkeypatch):
    pid, _ = make_paper()
    monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: pytest.fail('native text must not call OCR'))
    assert client.post(f'/api/papers/{pid}/document', json={}).status_code == 200
    state = finish(client, pid)
    assert state['status'] == 'ready' and state['completed_pages'] == 2 and state['ocr_pages'] == 0
    assert state['index_status'] == 'unconfigured'
    markdown = client.get(f'/api/papers/{pid}/document/markdown').json()['markdown']
    assert '<!-- page:2 -->' in markdown and 'original scientific' in markdown
    with Session(get_engine()) as session:
        assert session.get(Paper, pid).full_text == markdown
        run_id = session.get(PaperDocument, pid).run_id
    assert client.post(f'/api/papers/{pid}/document', json={}).json()['status'] == 'ready'
    with Session(get_engine()) as session:
        assert session.get(PaperDocument, pid).run_id == run_id
    response = client.get(f'/api/papers/{pid}/document/download?bundle=true')
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert set(bundle.namelist()) == {'document.md', 'page-1.png', 'page-2.png'}
        assert bundle.read('document.md').decode() == markdown
    assert client.get(f'/api/papers/{pid}/document/pages/1').headers['content-type'] == 'image/png'
    from app.archive.service import create_backup, resolve_backup, verify_backup
    with Session(get_engine()) as session:
        backup = create_backup(session)
    assert verify_backup(backup['filename'])['ok']
    with zipfile.ZipFile(resolve_backup(backup['filename'])) as bundle:
        assert any(name.endswith('/document.md') for name in bundle.namelist())
        assert any(name.endswith('/page-2.png') for name in bundle.namelist())


def test_ocr_failure_keeps_old_text_and_resumes_only_remaining_pages(client, monkeypatch):
    models(client)
    pid, _ = make_paper(scan=True)
    calls = []
    def complete(self, provider, model, messages, **kwargs):
        calls.append(messages)
        assert model == 'vision' and kwargs['request_kind'] == 'pdf_ocr'
        assert messages[0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
        if len(calls) == 2:
            raise RuntimeError('secret key must not appear')
        return SimpleNamespace(content='## Method\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n$x^2$')
    monkeypatch.setattr(ProviderClient, 'complete', complete)
    monkeypatch.setattr(ProviderClient, 'embed', lambda *a, **kw: [[1., 0.]] * len(a[3]))
    assert client.post(f'/api/papers/{pid}/document', json={}).status_code == 200
    state = finish(client, pid)
    assert state['status'] == 'error' and state['completed_pages'] == 1
    assert 'secret' not in state['error']
    with Session(get_engine()) as session:
        assert session.get(Paper, pid).full_text == 'Previous text'
    client.post(f'/api/papers/{pid}/document', json={})
    assert finish(client, pid)['status'] == 'ready'
    assert len(calls) == 3
    with Session(get_engine()) as session:
        assert '| A | B |' in session.get(Paper, pid).full_text
        chunks = session.exec(select(PaperChunk).where(PaperChunk.paper_id == pid)).all()
        assert any('[第 2 页]' in c.text and '\n|---|---|' in c.text for c in chunks)


def test_cancel_discards_late_result_and_duplicate_job(client, monkeypatch):
    models(client)
    pid, _ = make_paper(scan=True)
    entered, release = Event(), Event()
    def complete(*a, **kw):
        entered.set(); assert release.wait(5)
        return SimpleNamespace(content='Late result')
    monkeypatch.setattr(ProviderClient, 'complete', complete)
    client.post(f'/api/papers/{pid}/document', json={'mode': 'ocr'})
    try:
        assert entered.wait(5)
        assert client.post(f'/api/papers/{pid}/document', json={'mode': 'ocr'}).status_code == 409
        assert client.post(f'/api/papers/{pid}/document/cancel').json()['status'] == 'cancelled'
    finally:
        release.set()
    state = finish(client, pid)
    assert state['status'] == 'cancelled' and state['completed_pages'] == 0
    with Session(get_engine()) as session:
        assert session.get(Paper, pid).full_text == 'Previous text'


def test_source_change_prevents_publication(client, monkeypatch):
    models(client)
    pid, path = make_paper(pages=1, scan=True)
    def complete(*a, **kw):
        with path.open('ab') as f:
            f.write(b'\n% source changed\n')
        return SimpleNamespace(content='Obsolete result')
    monkeypatch.setattr(ProviderClient, 'complete', complete)
    client.post(f'/api/papers/{pid}/document', json={'mode': 'ocr'})
    assert 'PDF 已变更' in finish(client, pid)['error']
    with Session(get_engine()) as session:
        assert session.get(Paper, pid).full_text == 'Previous text'


def test_scan_without_model_and_restart_state_are_actionable(client):
    pid, _ = make_paper(scan=True)
    assert client.post(f'/api/papers/{pid}/document', json={'mode': 'ocr'}).status_code == 422
    client.post(f'/api/papers/{pid}/document', json={})
    state = finish(client, pid)
    assert state['status'] == 'error' and '选择' in state['error']
    with Session(get_engine()) as session:
        row = session.get(PaperDocument, pid); row.status = 'running'
        session.add(row); session.commit()
    assert client.get(f'/api/papers/{pid}/document').json()['status'] == 'interrupted'


def test_model_roles_validate_and_reranker_never_becomes_chat(client):
    ids = models(client)
    for value in [str(ids['vector']), '99999', 'bad', '0']:
        assert client.put('/api/settings/ocr_model_config_id', json={'value': value}).status_code == 422
    for name in ['vision', 'chat', 'vector']:
        assert client.put('/api/settings/rerank_model_config_id', json={'value': str(ids[name])}).status_code == 422
    assert client.put('/api/settings/rerank_model_config_id', json={'value': str(ids['ranker'])}).status_code == 200
    assert ids['ranker'] not in [m['id'] for m in client.get('/api/chat/models').json()]
    assert client.put('/api/settings/translation_model_config_id', json={'value': str(ids['ranker'])}).status_code == 422
    assert client.patch(f'/api/models/{ids["ranker"]}', json={'role_default': 'chat'}).status_code == 422
    assert client.patch(f'/api/models/{ids["vision"]}', json={'supports_images': False}).status_code == 422


def test_rerank_candidates_are_scoped_and_failure_falls_back(client, monkeypatch):
    from app.rag.index import retrieve
    from app.rag.vector import serialize
    ids = models(client)
    client.put('/api/settings/rerank_model_config_id', json={'value': str(ids['ranker'])})
    with Session(get_engine()) as session:
        a, b = Paper(title='A', source='manual'), Paper(title='B', source='manual')
        session.add_all([a, b]); session.commit(); session.refresh(a); session.refresh(b)
        for paper, text, vector in [(a, 'Near', [1, 0]), (a, 'Better answer', [.7, .3]), (b, 'Private outside scope', [1, 0])]:
            session.add(PaperChunk(paper_id=paper.id, text=text, ordinal=0, embedding=serialize(vector), embedding_model='vector'))
        session.commit()
        monkeypatch.setattr(ProviderClient, 'embed', lambda *a, **kw: [[1, 0]])
        def rerank(self, provider, model, query, docs, top_n):
            assert docs == ['Near', 'Better answer'] and model == 'ranker'
            return [(1, .95)]
        monkeypatch.setattr(ProviderClient, 'rerank', rerank)
        assert retrieve(session, 'question', k=1, paper_ids=[a.id])[0][0].text == 'Better answer'
        monkeypatch.setattr(ProviderClient, 'rerank', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('offline')))
        assert retrieve(session, 'question', k=1, paper_ids=[a.id])[0][0].text == 'Near'
        assert retrieve(session, 'question', paper_ids=[]) == []


@pytest.mark.parametrize('results', [[{'index': 99, 'relevance_score': .5}], [{'index': 0, 'relevance_score': float('nan')}], [{'index': 0, 'relevance_score': .5}, {'index': 0, 'relevance_score': .4}], []])
def test_rerank_rejects_invalid_provider_results(client, monkeypatch, results):
    from app.providers.purposes import purpose_model
    ids = models(client)
    client.put('/api/settings/rerank_model_config_id', json={'value': str(ids['ranker'])})
    import httpx
    def post(url, **kwargs):
        assert url == 'https://example.test/v1/rerank'
        assert kwargs['json']['documents'] == ['One'] and kwargs['timeout'] == 20
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'results': results})
    monkeypatch.setattr(httpx, 'post', post)
    with Session(get_engine()) as session:
        rclient, provider, model = purpose_model(session, 'rerank')
        with pytest.raises(ValueError):
            rclient.rerank(provider, model, 'Q', ['One'], 1)


def test_truncated_ocr_response_is_never_published(client, monkeypatch):
    import litellm
    from app.providers.purposes import purpose_model
    models(client)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Partial text'), finish_reason='length')], usage=None)
    monkeypatch.setattr(litellm, 'completion', lambda **kw: response)
    with Session(get_engine()) as session:
        caller, provider, model = purpose_model(session, 'ocr')
        with pytest.raises(ValueError, match='truncated'):
            caller.complete(provider, model, [{'role': 'user', 'content': 'transcribe'}], request_kind='pdf_ocr')


def test_document_jobs_and_model_settings_are_project_scoped(client):
    from app.workspaces.context import bind_workspace
    contexts = []
    for name in ['OCR project A', 'OCR project B']:
        wid = client.post('/api/workspaces', json={'name': name}).json()['id']
        context = client.app.state.workspaces.context(wid)
        contexts.append(context)
        with bind_workspace(context):
            make_paper(pages=1)
    a, b = ['/api/w/' + context.id for context in contexts]
    provider = client.post(a + '/providers', json={'name': 'A vision', 'type': 'openai_chat'}).json()['id']
    mid = client.post(a + f'/providers/{provider}/models', json={'model_id': 'vision'}).json()['id']
    assert client.put(a + '/settings/ocr_model_config_id', json={'value': str(mid)}).status_code == 200
    assert 'ocr_model_config_id' not in client.get(b + '/settings').json()
    assert client.post(a + '/papers/1/document', json={}).status_code == 200
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(a + '/papers/1/document').json()
        if state['status'] == 'ready' and state['index_status'] != 'pending':
            break
        time.sleep(.02)
    assert state['status'] == 'ready'
    assert client.get(b + '/papers/1/document').json()['status'] == 'idle'
    assert client.get(b + '/papers/1/document/markdown').status_code == 404
    with bind_workspace(contexts[1]), Session(get_engine()) as session:
        assert session.get(Paper, 1).full_text == 'Previous text'
