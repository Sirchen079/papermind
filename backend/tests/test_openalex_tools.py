import json

import httpx
from sqlmodel import Session

from app.agent import openalex
from app.agent.openalex import find_related_openalex, search_openalex
from app.agent.provenance import tool_sources
from app.db.engine import get_engine
from app.models import Setting


def install(monkeypatch, handler):
    monkeypatch.setattr(openalex, '_client', lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def work(wid='W1', title='Dense passage retrieval', year=2020, abstract=True):
    inverted = {'retrieval': [0], 'passage': [1]} if abstract else None
    return {
        'id': f'https://openalex.org/{wid}',
        'doi': 'https://doi.org/10.1000/demo',
        'display_name': title,
        'publication_year': year,
        'authorships': [{'author': {'display_name': 'A. Author'}}],
        'primary_location': {'source': {'display_name': 'Journal of Tests'}},
        'cited_by_count': 42,
        'open_access': {'is_oa': True},
        'best_oa_location': {'pdf_url': 'https://example.test/paper.pdf'},
        'abstract_inverted_index': inverted,
    }


def db_session():
    return Session(get_engine())


def test_search_returns_records_and_web_sources(client, monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={'results': [work()]}))
    with db_session() as db:
        raw = search_openalex(db, 'dense retrieval')
    rows = json.loads(raw)
    assert rows[0]['type'] == 'web' and rows[0]['url'] == 'https://example.test/paper.pdf'
    assert rows[0]['oa_pdf_url'] and rows[0]['cited_by_count'] == 42
    assert rows[0]['text'].startswith('retrieval passage')
    with db_session() as db:
        sources = tool_sources(db, 'search_openalex', raw)
    assert sources and sources[0]['source_type'] == 'web'
    assert sources[0]['url'] == 'https://example.test/paper.pdf'


def test_search_adds_mailto_and_reports_errors(client, monkeypatch):
    seen = {}

    def handler(request):
        seen['url'] = str(request.url)
        return httpx.Response(500, json={})

    install(monkeypatch, handler)
    with db_session() as db:
        db.add(Setting(key='openalex_mailto', value='researcher@example.test'))
        db.commit()
        raw = search_openalex(db, 'topic')
    assert 'mailto=researcher%40example.test' in seen['url']
    assert json.loads(raw)['error_type'] == 'openalex'
    with db_session() as db:
        raw = search_openalex(db, '')
    assert json.loads(raw)['error'] == 'empty query'


def test_search_without_abstract_still_records_text(client, monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={'results': [work(abstract=False)]}))
    with db_session() as db:
        raw = search_openalex(db, 'dense retrieval')
    rows = json.loads(raw)
    assert rows[0]['text']  # provenance fallback line: title (venue, year)


def test_survey_retains_complete_authors_while_agent_uses_short_preview(client, monkeypatch):
    from app.literature.survey import _search_phrase
    record = work()
    names = [f'Author {i}' for i in range(15)]
    record['authorships'] = [{'author':{'display_name':name}} for name in names]
    install(monkeypatch, lambda request: httpx.Response(200, json={'results':[record]}))
    with db_session() as db:
        candidates = _search_phrase(db,'retrieval',2025,25)
        preview = json.loads(search_openalex(db,'retrieval'))
    assert candidates[0]['authors'] == names
    assert preview[0]['authors'] == names[:6]


def test_search_reports_empty_results(client, monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={'results': []}))
    with db_session() as db:
        raw = search_openalex(db, 'nothing matches')
    assert 'note' in json.loads(raw)


def test_oa_landing_page_is_not_a_pdf_download(client, monkeypatch):
    record = work()
    record['best_oa_location'] = {'pdf_url': None, 'landing_page_url': 'https://example.test/article'}
    install(monkeypatch, lambda request: httpx.Response(200, json={'results': [record]}))
    with db_session() as db:
        rows = json.loads(search_openalex(db, 'dense retrieval'))
    assert rows[0]['is_oa'] is True
    assert rows[0]['url'] == 'https://example.test/article'
    assert rows[0]['oa_pdf_url'] is None


def test_related_work_ids_use_one_or_filter(client, monkeypatch):
    def handler(request):
        if request.url.path == '/works/W1':
            return httpx.Response(200, json={'related_works': ['https://openalex.org/W7', 'https://openalex.org/W8']})
        assert request.url.params['filter'] == 'openalex_id:W7|W8'
        assert request.url.params['per-page'] == '2'
        return httpx.Response(200, json={'results': [work(wid='W7'), work(wid='W8')]})

    install(monkeypatch, handler)
    with db_session() as db:
        rows = json.loads(find_related_openalex(db, openalex_id='W1', limit=2))
    assert {row['openalex_id'] for row in rows} == {'W7', 'W8'}


def test_find_related_resolves_doi_then_fetches_works(client, monkeypatch):
    requests = []

    def handler(request: httpx.Request):
        requests.append((request.url.path, str(request.url)))
        if request.url.path.startswith('/works/doi:'):
            return httpx.Response(200, json={'related_works': ['https://openalex.org/W7']})
        return httpx.Response(200, json={'results': [work(wid='W7', title='Follow-up work')]})

    install(monkeypatch, handler)
    with db_session() as db:
        raw = find_related_openalex(db, doi='10.1000/demo')
    rows = json.loads(raw)
    assert rows[0]['title'] == 'Follow-up work'
    assert any(path.startswith('/works/doi:') for path, _ in requests)
    assert any('filter=openalex_id%3AW7' in url or 'filter=openalex_id:W7' in url for _, url in requests)
    with db_session() as db:
        assert json.loads(find_related_openalex(db))['error'] == 'doi or openalex_id required'


def test_tools_registered_in_schema(client):
    from app.agent.tools import get_tool

    assert get_tool('search_openalex') is not None
    assert get_tool('find_related_openalex') is not None
    assert 'OpenAlex' in get_tool('search_openalex').description
