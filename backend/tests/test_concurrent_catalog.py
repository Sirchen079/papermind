from concurrent.futures import ThreadPoolExecutor
import time

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Paper


def test_concurrent_metadata_import_deduplicates_before_commit(client, monkeypatch, tmp_path):
    from app.ingestion import service
    from app.ingestion.sources import FetchedPaper
    original = service.find_duplicate

    def delayed(*args, **kwargs):
        row = original(*args, **kwargs)
        time.sleep(0.1)
        return row

    monkeypatch.setattr(service, 'find_duplicate', delayed)
    def ingest(_):
        with Session(get_engine()) as session:
            return service.persist_fetched(session, FetchedPaper(source='bibtex', title='Concurrent import', doi='10.synthetic/same'), tmp_path / 'pdfs').id
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(ingest, range(6)))
    assert len(set(ids)) == 1
    with Session(get_engine()) as session:
        assert len(session.exec(select(Paper)).all()) == 1


def test_concurrent_manual_creation_keeps_identifiers_unique(client, monkeypatch):
    from app.api import papers_api
    original = papers_api._ensure_unique_title
    def delayed(*args):
        original(*args)
        time.sleep(0.1)
    monkeypatch.setattr(papers_api, '_ensure_unique_title', delayed)
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: client.post('/api/papers/manual', json={'title':'Concurrent manual'}), range(6)))
    assert sorted(row.status_code for row in responses) == [201, 422, 422, 422, 422, 422]


def test_refresh_duplicate_provider_model_ids_is_idempotent(client, monkeypatch):
    from app.api.providers_api import ProviderClient
    from app.providers.client import ModelInfo
    pid = client.post('/api/providers', json={'name':'Refresh duplicate','type':'openai_chat'}).json()['id']
    monkeypatch.setattr(ProviderClient, 'list_models', lambda *_: [ModelInfo(model_id='duplicate'), ModelInfo(model_id='duplicate')])
    assert client.post(f'/api/providers/{pid}/models/refresh').status_code == 200
    assert len(client.get(f'/api/providers/{pid}/models').json()) == 1


def test_concurrent_manual_models_keep_one_default(client):
    pid = client.post('/api/providers', json={'name':'Manual roles','type':'openai_chat'}).json()['id']
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: client.post(f'/api/providers/{pid}/models', json={'model_id':f'manual-{i}', 'role_default':'chat'}), range(6)))
    assert all(row.status_code == 201 for row in results)
    assert sum(row['role_default'] == 'chat' for row in client.get('/api/models').json()) == 1


def test_concurrent_pdf_uploads_share_one_complete_original(client, tmp_path):
    import fitz
    from app.ingestion.service import persist_fetched
    from app.ingestion.sources import FetchedPaper
    with fitz.open() as doc:
        doc.new_page().insert_text((72,72), 'Concurrent synthetic PDF')
        data = doc.tobytes()
    def ingest(i):
        with Session(get_engine()) as session:
            return persist_fetched(session, FetchedPaper(source='pdf', title=f'renamed-{i}.pdf', pdf_bytes=data), tmp_path / 'pdfs').id
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(ingest, range(6)))
    assert len(set(ids)) == 1
    assert [path.read_bytes() for path in (tmp_path / 'pdfs').glob('*.pdf')] == [data]


def test_concurrent_external_add_is_idempotent_and_queues_once(client):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: client.post('/api/papers/from-external', json={'title':'External concurrency'}), range(6)))
    assert all(row.status_code == 201 for row in results)
    assert len({row.json()['paper']['id'] for row in results}) == 1
    assert sum(row.json()['created'] for row in results) == 1


def test_model_refresh_does_not_recreate_models_after_provider_deletion(client, monkeypatch):
    from threading import Event
    from app.api.providers_api import ProviderClient
    from app.providers.client import ModelInfo
    entered, release = Event(), Event()
    def paused(*_):
        entered.set()
        assert release.wait(10)
        return [ModelInfo(model_id='late-model')]
    monkeypatch.setattr(ProviderClient, 'list_models', paused)
    pid = client.post('/api/providers', json={'name':'Deleted during refresh','type':'openai_chat'}).json()['id']
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f'/api/providers/{pid}/models/refresh')
        try:
            assert entered.wait(10)
            assert client.delete(f'/api/providers/{pid}').status_code == 204
        finally:
            release.set()
        assert future.result().status_code == 404
    assert client.get(f'/api/providers/{pid}/models').json() == []
