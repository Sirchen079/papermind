import json
from threading import Event
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Paper, PaperChunk, PaperDocument, Setting
from app.providers.client import ProviderClient
from app.reading import documents
from test_documents import finish, make_paper, models
from test_pdf_markdown_pipeline import imported, mixed_imported


def test_configured_ocr_is_not_used_for_readable_import_and_embedding_reads_published_markdown(client, monkeypatch):
    models(client)
    vectors = []
    monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: pytest.fail('readable PDF must not call OCR'))
    def embed(self, provider, model, texts, **kwargs):
        with Session(get_engine()) as session:
            paper = session.exec(select(Paper)).one()
            document = session.get(PaperDocument, paper.id)
            assert paper.full_text == document.markdown and '<!-- page:1 -->' in document.markdown
        vectors.extend(texts)
        return [[1., 0.]] * len(texts)
    monkeypatch.setattr(ProviderClient, 'embed', embed)
    pid = imported(client)
    state = finish(client, pid)
    assert state['status'] == 'ready' and state['native_pages'] == state['completed_pages'] == 2
    assert state['ocr_pages'] == state['pending_ocr_pages'] == 0
    assert vectors and any('[第 2 页]' in text for text in vectors)
    with Session(get_engine()) as session:
        pages = json.loads(session.get(PaperDocument, pid).pages_json)
        assert all(page['text_quality']['reliable'] for page in pages)
        assert all(chunk.embedding for chunk in session.exec(select(PaperChunk)))


def test_waiting_scan_resumes_on_model_configuration_without_repeating_good_pages(client, monkeypatch):
    calls, extracted = [], []
    original = documents.native_page
    def native(page):
        extracted.append(page.number)
        return original(page)
    monkeypatch.setattr(documents, 'native_page', native)
    monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: calls.append(kw['request_kind']) or SimpleNamespace(content='Recovered old scanned evidence'))
    monkeypatch.setattr(ProviderClient, 'embed', lambda *a, **kw: [[1., 0.]] * len(a[3]))
    pid = mixed_imported(client)
    state = finish(client, pid)
    assert state['status'] == 'waiting_model' and state['has_markdown']
    assert state['completed_pages'] == state['native_pages'] == state['pending_ocr_pages'] == 1
    with Session(get_engine()) as session:
        assert not json.loads(session.get(PaperDocument, pid).followup_json).get('finished')
    extracted.clear()
    models(client)  # Selecting the model resumes the waiting import automatically.
    state = finish(client, pid)
    assert state['status'] == 'ready' and state['completed_pages'] == 2 and state['pending_ocr_pages'] == 0
    assert calls == ['pdf_ocr'] and extracted == [1]
    with Session(get_engine()) as session:
        paper, row = session.get(Paper, pid), session.get(PaperDocument, pid)
        assert 'Page 1' in paper.full_text and 'Recovered old scanned evidence' in paper.full_text
        assert paper.full_text.count('<!-- page:1 -->') == paper.full_text.count('<!-- page:2 -->') == 1
        assert json.loads(row.followup_json)['finished']


def test_bad_text_is_not_published_as_searchable_evidence_without_ocr(client, monkeypatch):
    original = documents.native_page
    def native(page):
        if page.number == 0:
            return 'unreadable \ufffd\ue001 body', {'reliable': False, 'coverage': .9, 'garble_rate': .9}
        return original(page)
    monkeypatch.setattr(documents, 'native_page', native)
    pid = imported(client)
    state = finish(client, pid)
    assert state['status'] == 'waiting_model' and state['completed_pages'] == 1
    with Session(get_engine()) as session:
        text = session.get(Paper, pid).full_text
        assert 'unreadable' not in text and '[此页需要 OCR，尚未转换]' in text and 'Page 2' in text


def test_unavailable_ocr_model_does_not_block_a_readable_text_layer(client, monkeypatch):
    with Session(get_engine()) as session:
        session.add(Setting(key='ocr_model_config_id', value='999999'))
        session.commit()
    monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: pytest.fail('no OCR needed'))
    pid = imported(client)
    state = finish(client, pid)
    assert state['status'] == 'ready' and state['ocr_pages'] == 0


def test_explicit_ocr_does_not_depend_on_the_text_layer_extractor(client, monkeypatch):
    models(client)
    pid, _ = make_paper(pages=1)
    def unavailable(*args):
        raise RuntimeError('broken text layer')
    monkeypatch.setattr(documents, 'native_page', unavailable)
    monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: SimpleNamespace(content='Recovered by explicit OCR'))
    monkeypatch.setattr(ProviderClient, 'embed', lambda *a, **kw: [[1., 0.]] * len(a[3]))
    client.post(f'/api/papers/{pid}/document', json={'mode': 'ocr'}).raise_for_status()
    state = finish(client, pid)
    assert state['status'] == 'ready' and state['ocr_pages'] == 1


@pytest.mark.parametrize('stage', ['extract', 'index'])
def test_model_selected_during_conversion_is_not_missed_by_the_waiting_queue(client, monkeypatch, stage):
    from app.rag import index
    entered, release = Event(), Event()
    calls, extracted = [], []
    original_native, original_index = documents.native_page, index.index_local_paper
    def pause():
        if not entered.is_set():
            entered.set()
            assert release.wait(15)
    def native(page):
        extracted.append(page.number)
        if stage == 'extract' and page.number == 1:
            pause()
        return original_native(page)
    def local(*args, **kwargs):
        if stage == 'index':
            pause()
        return original_index(*args, **kwargs)
    monkeypatch.setattr(documents, 'native_page', native)
    monkeypatch.setattr(index, 'index_local_paper', local)
    monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: calls.append(1) or SimpleNamespace(content='Recovered during model configuration'))
    monkeypatch.setattr(ProviderClient, 'embed', lambda *a, **kw: [[1., 0.]] * len(a[3]))
    pid = mixed_imported(client)
    try:
        assert entered.wait(10)
        models(client)
    finally:
        release.set()
    state = finish(client, pid)
    assert state['status'] == 'ready' and state['ocr_pages'] == 1
    assert calls == [1] and extracted.count(0) == 1
    if stage == 'extract':
        assert extracted.count(1) == 1
