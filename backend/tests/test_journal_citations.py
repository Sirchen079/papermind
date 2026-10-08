import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlmodel import Session

from app.archive.bibtex import format_paper as bibtex
from app.archive.ris import format_paper as ris
from app.db.engine import get_engine
from app.ingestion.sources import fetch_crossref, parse_bibtex, parse_ris
from app.models import Paper

BIB = '''@article{Choi2012, title={Application of global correlation},
author={Choi, Yunseok and Alkhalifah, Tariq}, year={2012},
journal={Geophysical Prospecting}, volume={60}, number={4}, pages={748–758},
doi={10.1111/j.1365-2478.2012.01079.x}}'''
DOI = '10.1111/j.1365-2478.2012.01079.x'
RECORD = {'DOI':DOI, 'title':['Application of global correlation'],
          'author':[{'family':'Choi','given':'Yunseok'}, {'family':'Alkhalifah','given':'Tariq'}],
          'container-title':['Geophysical Prospecting'], 'volume':'60', 'issue':'4',
          'page':'748–758', 'published-print':{'date-parts':[[2012,7]]}}


@pytest.mark.parametrize('identifier', [DOI.upper(), 'doi: ' + DOI, 'https://doi.org/' + DOI])
def test_crossref_requests_exact_identifier_and_preserves_citation_fields(monkeypatch, identifier):
    def get(url, **kwargs):
        assert url == 'https://api.crossref.org/works/10.1111%2Fj.1365-2478.2012.01079.x'
        assert kwargs['timeout'] == 15
        return httpx.Response(200, json={'message':RECORD}, request=httpx.Request('GET', url))
    monkeypatch.setattr('app.security.url_guard.validated_get', get)
    p = fetch_crossref(identifier)
    assert (p.volume, p.issue, p.pages) == ('60', '4', '748–758')
    assert p.authors == ['Choi, Yunseok', 'Alkhalifah, Tariq']
    assert p.source == 'crossref' and p.doi == DOI


def test_wrong_doi_is_not_attached_as_metadata(monkeypatch):
    monkeypatch.setattr('app.security.url_guard.validated_get', lambda url, **kw:
        httpx.Response(200, json={'message':{**RECORD,'DOI':'10.1000/wrong'}}, request=httpx.Request('GET', url)))
    with pytest.raises(ValueError, match='requested DOI'):
        fetch_crossref(DOI)


def test_crossref_keeps_print_year_article_number_and_all_authors(monkeypatch):
    record = {**RECORD, 'published-online':{'date-parts':[[2025,11,13]]},
              'issued':{'date-parts':[[2025,11,13]]}, 'published-print':{'date-parts':[[2026,3,1]]},
              'page':None, 'article-number':'e2025JH000123',
              'author':[{'family':f'Family{i}','given':f'Given{i}'} for i in range(15)]}
    monkeypatch.setattr('app.security.url_guard.validated_get', lambda url, **kw:
        httpx.Response(200, json={'message':record}, request=httpx.Request('GET', url)))
    paper = fetch_crossref(DOI)
    assert paper.year == 2026 and paper.pages == 'e2025JH000123'
    assert paper.authors == [f'Family{i}, Given{i}' for i in range(15)]


def test_crossref_online_only_dates_and_group_authors(monkeypatch):
    record = {**RECORD, 'published-print':{'date-parts':[[None]]},
              'published-online':{'date-parts':[[2025,11,13]]},
              'author':[{'name':'Example Research Consortium'}, {'family':'董','given':'兴朋'}]}
    monkeypatch.setattr('app.security.url_guard.validated_get', lambda url, **kw:
        httpx.Response(200, json={'message':record}, request=httpx.Request('GET', url)))
    paper = fetch_crossref(DOI)
    assert paper.year == 2025 and paper.authors == ['Example Research Consortium','董, 兴朋']


def test_concurrent_citation_lookups_share_public_api_limit(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    import time
    state = {'active':0, 'maximum':0, 'calls':0}
    lock = Lock()
    def get(url, **kwargs):
        with lock:
            state['active'] += 1
            state['maximum'] = max(state['maximum'],state['active'])
            state['calls'] += 1
        time.sleep(.05)
        with lock:
            state['active'] -= 1
        return httpx.Response(200,json={'message':RECORD},request=httpx.Request('GET',url))
    monkeypatch.setattr('app.security.url_guard.validated_get',get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(fetch_crossref,[DOI,DOI]))
    assert state['calls'] == 2 and state['maximum'] == 1
    assert all(p.doi == DOI for p in records)


@pytest.mark.parametrize('pages,expected', [
    ('748–758', '748--758'), ('S1-S9', 'S1--S9'), ('e012345', 'e012345'),
    ('101', '101'), ('1--4, 9--12', '1--4, 9--12'),
])
def test_page_ranges_and_article_numbers_roundtrip(pages, expected):
    p = Paper(source='manual', title='Journal article', volume='60', issue='S1', pages=pages)
    from_bib = parse_bibtex(bibtex(p, 'key'))[0]
    from_ris = parse_ris(ris(p))[0]
    assert (from_bib.volume, from_bib.issue, from_bib.pages) == ('60', 'S1', pages)
    assert (from_ris.volume, from_ris.issue, from_ris.pages) == ('60', 'S1', expected)


def test_import_edit_clear_export_and_project_copy(client):
    imported = client.post('/api/papers/bibtex', json={'bibtex': BIB})
    assert imported.status_code == 200, imported.text
    papers = client.get('/api/papers').json()
    # List endpoint supports pagination in some callers; this is the default list.
    p = papers[0] if isinstance(papers, list) else papers['items'][0]
    pid = p['id']
    assert (p['volume'], p['issue'], p['pages']) == ('60', '4', '748–758')
    saved = client.patch(f'/api/papers/{pid}', json={'volume': ' 60 ', 'issue': 'S1', 'pages': 'S1--S9'})
    assert saved.status_code == 200 and saved.json()['volume'] == '60'
    for fmt, parse in [('bibtex', parse_bibtex), ('ris', parse_ris)]:
        exported = client.get('/api/archive/export/' + fmt)
        assert exported.status_code == 200
        row = parse(exported.text)[0]
        assert (row.volume, row.issue, row.pages) == ('60', 'S1', 'S1--S9')
    archive = client.get('/api/archive/export/json').json()
    assert archive['papers'][0]['pages'] == 'S1--S9'
    target = client.post('/api/workspaces', json={'name': 'Citation destination'}).json()['id']
    copied = client.post(f'/api/papers/{pid}/copy-to-workspace', json={
        'target_workspace': target, 'request_id': uuid4().hex})
    assert copied.status_code == 201, copied.text
    clone = client.get(f'/api/w/{target}/papers/{copied.json()["paper_id"]}').json()
    assert (clone['volume'], clone['issue'], clone['pages']) == ('60', 'S1', 'S1--S9')
    cleared = client.patch(f'/api/papers/{pid}', json={'issue': None}).json()
    assert cleared['issue'] is None and cleared['pages'] == 'S1--S9'
    assert client.get(f'/api/w/{target}/papers/{clone["id"]}').json()['issue'] == 'S1'
    manual = client.post('/api/papers/manual', json={'title': 'Article number', 'volume': '9', 'pages': 'e021'})
    assert manual.status_code == 201 and manual.json()['pages'] == 'e021'
    imported_ris = client.post('/api/papers/ris', json={'ris':
        'TY  - JOUR\nTI  - RIS journal\nVL  - 10\nIS  - 2\nSP  - S8\nEP  - S12\nER  -'})
    assert imported_ris.status_code == 200, imported_ris.text
    with Session(get_engine()) as session:
        from sqlmodel import select
        record = session.exec(select(Paper).where(Paper.title == 'RIS journal')).one()
        assert (record.volume, record.issue, record.pages) == ('10', '2', 'S8--S12')


def test_journal_pdf_metadata_success_failure_and_curated_record(client, monkeypatch):
    client.put('/api/settings/pdf_ingest_mode', json={'value': 'manual'}).raise_for_status()
    from test_paper_acquisition import network, pdf
    from app.agent.paper_acquisition import import_paper_pdf
    network(monkeypatch, lambda req: httpx.Response(200, content=pdf()))
    calls = []
    def metadata(doi):
        calls.append(doi)
        return parse_bibtex(BIB)[0]
    monkeypatch.setattr('app.ingestion.sources.fetch_crossref', metadata)
    with Session(get_engine()) as s:
        first = json.loads(import_paper_pdf(s, 'https://archive.example/journal.pdf', title='Verified title', doi=DOI))
        p = s.get(Paper, first['paper_id'])
        assert (p.title, p.volume, p.issue, p.pages) == ('Verified title', '60', '4', '748–758')
        assert first['metadata']['source'] == 'crossref' and first['metadata']['status'] == 'retrieved'
        assert json.loads(Path(p.pdf_path).with_suffix('.source.json').read_text())['metadata'] == first['metadata']
        repeat = json.loads(import_paper_pdf(s, 'https://archive.example/journal.pdf', doi=DOI))
        assert repeat['status'] == 'already_available' and len(calls) == 1
        curated = Paper(source='manual', title='Curated title', doi='10.1000/curated', volume='Chosen', pages='e009')
        s.add(curated); s.commit()
        import_paper_pdf(s, 'https://archive.example/curated.pdf', paper_id=curated.id)
        assert (curated.volume, curated.pages) == ('Chosen', 'e009') and len(calls) == 1
        def unavailable(doi):
            raise httpx.ReadTimeout('offline')
        monkeypatch.setattr('app.ingestion.sources.fetch_crossref', unavailable)
        failed = json.loads(import_paper_pdf(s, 'https://archive.example/offline.pdf', title='Available PDF', doi='10.1000/offline'))
        assert failed['metadata']['status'] == 'unavailable'
        assert failed['pages'] == 2 and failed['full_text_chars'] > 0


def test_legacy_migration_retains_existing_rows_and_is_fresh_schema_compatible(tmp_path):
    from alembic import command
    from alembic.config import Config
    from app import paths
    from app.db.engine import make_engine
    from sqlalchemy import text
    engine = make_engine(tmp_path / 'legacy.sqlite')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE paper (id INTEGER PRIMARY KEY, title TEXT, doi TEXT)'))
        c.execute(text("INSERT INTO paper VALUES (7,'Original citation',:doi)"), {'doi': DOI})
    cfg = Config(str(paths.alembic_ini()))
    cfg.set_main_option('script_location', str(paths.migrations_dir()))
    cfg.set_main_option('sqlalchemy.url', str(engine.url))
    command.stamp(cfg, 'f0718b9c2001'); command.upgrade(cfg, 'head')
    with engine.connect() as c:
        assert c.execute(text('SELECT * FROM paper')).one() == (7, 'Original citation', DOI, None, None, None)
    # create_all-before-migration startup path: already present columns are safe.
    command.stamp(cfg, 'f0718b9c2001'); command.upgrade(cfg, 'head')
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM paper')).scalar_one() == 1
