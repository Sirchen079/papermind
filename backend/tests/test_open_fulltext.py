import json

import pytest
from sqlmodel import Session

from app.db.engine import get_engine
from app.ingestion.enrich import fetch_open_fulltext, open_access_pdf_urls
from app.models import Paper

WORK = {
    'best_oa_location': {'pdf_url': 'https://a.org/best.pdf'},
    'locations': [
        {'pdf_url': 'https://a.org/best.pdf', 'is_oa': True},
        {'pdf_url': 'https://b.org/oa.pdf', 'is_oa': True},
        {'pdf_url': 'https://c.org/closed.pdf', 'is_oa': False},
        {'pdf_url': None, 'is_oa': True},
    ],
}


class FakeResponse:
    status_code = 200

    def json(self):
        return WORK


class NoOaResponse:
    status_code = 200

    def json(self):
        return NO_OA_WORK


class FakeClient:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, params=None):
        return FakeResponse()


class NoOaClient(FakeClient):
    def get(self, url, params=None):
        return NoOaResponse()


NO_OA_WORK = {'best_oa_location': None, 'locations': [{'pdf_url': 'https://c.org/closed.pdf', 'is_oa': False}]}


def _add_paper(client, **kwargs):
    with Session(get_engine()) as s:
        paper = Paper(source='manual', title='Fulltext fixture', **kwargs)
        s.add(paper)
        s.commit()
        s.refresh(paper)
        pid = paper.id
    return pid


def test_open_access_pdf_urls_orders_best_first_dedups_and_filters(client, monkeypatch):
    monkeypatch.setattr('app.agent.openalex._client', FakeClient)
    with Session(get_engine()) as s:
        assert open_access_pdf_urls(s, '10.1000/x') == ['https://a.org/best.pdf', 'https://b.org/oa.pdf']


def test_open_access_pdf_urls_network_error_returns_empty(client, monkeypatch):
    class BoomClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None):
            raise RuntimeError('offline')

    monkeypatch.setattr('app.agent.openalex._client', lambda: BoomClient())
    with Session(get_engine()) as s:
        assert open_access_pdf_urls(s, '10.1000/x') == []


def test_existing_pdf_returns_has_pdf_without_download(client, monkeypatch):
    monkeypatch.setattr('app.agent.paper_acquisition.import_paper_pdf',
                        lambda *a, **kw: pytest.fail('existing PDF must not be downloaded again'))
    pid = _add_paper(client, doi='10.1000/x', pdf_path='stored.pdf')
    with Session(get_engine()) as s:
        assert fetch_open_fulltext(s, s.get(Paper, pid)) == {'status': 'has_pdf'}


def test_first_link_failure_falls_through_to_second(client, monkeypatch):
    monkeypatch.setattr('app.agent.openalex._client', FakeClient)
    calls = []

    def fake_import(session, url, paper_id=None, **kw):
        calls.append(url)
        if url.endswith('best.pdf'):
            raise ValueError('not a pdf')
        return json.dumps({'ok': True})

    monkeypatch.setattr('app.agent.paper_acquisition.import_paper_pdf', fake_import)
    pid = _add_paper(client, doi='10.1000/x')
    with Session(get_engine()) as s:
        assert fetch_open_fulltext(s, s.get(Paper, pid)) == {'status': 'attached', 'url': 'https://b.org/oa.pdf'}
    assert calls == ['https://a.org/best.pdf', 'https://b.org/oa.pdf']


def test_all_links_failing_reports_tried_and_error_types(client, monkeypatch):
    monkeypatch.setattr('app.agent.openalex._client', FakeClient)
    calls = []

    def fake_import(session, url, paper_id=None, **kw):
        calls.append(url)
        raise ValueError('not a pdf')

    monkeypatch.setattr('app.agent.paper_acquisition.import_paper_pdf', fake_import)
    pid = _add_paper(client, doi='10.1000/x')
    with Session(get_engine()) as s:
        assert fetch_open_fulltext(s, s.get(Paper, pid)) == {'status': 'failed', 'tried': 2,
                                                             'error_types': ['ValueError', 'ValueError']}
    assert len(calls) == 2


def test_no_open_access_links_returns_no_open_access(client, monkeypatch):
    monkeypatch.setattr('app.agent.openalex._client', NoOaClient)
    monkeypatch.setattr('app.agent.paper_acquisition.import_paper_pdf',
                        lambda *a, **kw: pytest.fail('no links must not trigger downloads'))
    pid = _add_paper(client, doi='10.1000/x')
    with Session(get_engine()) as s:
        assert fetch_open_fulltext(s, s.get(Paper, pid)) == {'status': 'no_open_access'}


def test_missing_doi_returns_no_doi(client, monkeypatch):
    monkeypatch.setattr('app.agent.paper_acquisition.import_paper_pdf',
                        lambda *a, **kw: pytest.fail('no DOI must not trigger downloads'))
    pid = _add_paper(client)
    with Session(get_engine()) as s:
        assert fetch_open_fulltext(s, s.get(Paper, pid)) == {'status': 'no_doi'}


def test_fetch_fulltext_api_rejects_more_than_50_ids(client):
    res = client.post('/api/papers/fetch-open-fulltext', json={'paper_ids': list(range(1, 52))})
    assert res.status_code == 422


def test_fetch_fulltext_api_returns_results_and_counts(client, monkeypatch):
    monkeypatch.setattr('app.agent.paper_acquisition.import_paper_pdf',
                        lambda session, url, paper_id=None, **kw: (_ for _ in ()).throw(ValueError('not a pdf')))
    monkeypatch.setattr('app.agent.openalex._client', NoOaClient)
    pid = _add_paper(client, doi='10.1000/x')
    res = client.post('/api/papers/fetch-open-fulltext', json={'paper_ids': [pid]})
    assert res.status_code == 200
    body = res.json()
    assert body['counts'] == {'no_open_access': 1}
    assert body['results'][0]['paper_id'] == pid
