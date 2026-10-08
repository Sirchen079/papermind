import json
import time
from contextlib import contextmanager
from pathlib import Path

import pymupdf
import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.db.engine import get_engine
from app.literature import survey
from app.models import LiteratureCandidate, LiteratureSurvey, Model, Paper, PaperChunk, Provider


@pytest.fixture(autouse=True)
def offline_citation_lookup(monkeypatch):
    def unavailable(doi):
        raise RuntimeError('offline test')
    monkeypatch.setattr('app.ingestion.sources.fetch_crossref', unavailable)


def wait_for(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    result = condition()
    while not result and time.monotonic() < deadline:
        time.sleep(0.02)
        result = condition()
    return result


def fixture_pdf(tmp: Path) -> Path:
    path = tmp / 'oa.pdf'
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=300, height=400)
        page.insert_text((20, 30), 'Open access full text about waveform inversion.', fontsize=10)
        pdf.save(path)
    return path


def fake_records():
    return [
        {'openalex_id': 'W1', 'doi': '10.1000/fwi-2025', 'title': 'FWI objective functions 2025',
         'year': 2025, 'venue': 'Geophysics', 'authors': ['A. Author'], 'cited_by_count': 9,
         'oa_pdf_url': 'https://example.test/fwi2025.pdf', 'type': 'web', 'text': 'Abstract about FWI objectives.',
         'url': 'https://example.test/fwi2025.pdf'},
        {'openalex_id': 'W2', 'doi': '10.1000/fwi-2024', 'title': 'Robust inversion with noise',
         'year': 2024, 'venue': 'GJI', 'authors': ['B. Author'], 'cited_by_count': 4,
         'oa_pdf_url': None, 'type': 'web', 'text': 'Abstract about robust inversion.',
         'url': 'https://doi.org/10.1000/fwi-2024'},
        {'openalex_id': 'W3', 'doi': '', 'title': 'Existing library paper',
         'year': 2024, 'venue': '', 'authors': [], 'cited_by_count': 0,
         'oa_pdf_url': None, 'type': 'web', 'text': 'Already in the library.', 'url': ''},
    ]


def install_search(monkeypatch, records=None):
    records = fake_records() if records is None else records
    captured = {}

    def fake_search(session, phrase, from_year, per_page):
        captured['phrase'] = phrase
        captured['from_year'] = from_year
        return list(records)

    monkeypatch.setattr(survey, '_search_phrase', fake_search)
    monkeypatch.setattr(survey, '_expand', lambda ctx, query, survey_id: [query])
    monkeypatch.setattr(survey, 'SEARCH_PAUSE_SECONDS', 0)
    monkeypatch.setattr(survey, 'DOWNLOAD_PAUSE_SECONDS', 0)
    return captured


def create(client, **overrides):
    body = {'query': '近两年 FWI 目标函数论文', 'years': 2, 'max_results': 20, 'screen': False}
    body.update(overrides)
    return client.post('/api/literature/surveys', json=body)


def test_survey_run_lists_candidates(client, monkeypatch):
    captured = install_search(monkeypatch)
    created = create(client).json()
    assert created['status'] == 'queued'
    detail = wait_for(lambda: (lambda d: d if d['status'] not in {'queued', 'running'} else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    assert detail and detail['status'] == 'ready'
    assert detail['counts']['candidate'] == 3
    assert len(detail['candidates']) == 3
    assert captured['from_year'] >= 2025
    titles = [c['title'] for c in detail['candidates']]
    assert 'FWI objective functions 2025' in titles
    assert client.get('/api/literature/surveys').json()['items']


def test_survey_requires_query(client):
    assert create(client, query='  ').status_code == 422


def test_survey_keeps_authors_beyond_display_preview(client, monkeypatch):
    records = fake_records()[:1]
    records[0]['authors'] = [f'Author {i}' for i in range(15)]
    install_search(monkeypatch, records)
    created = create(client).json()
    state = wait_for(lambda: (lambda d: d if d['status'] == 'ready' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    assert state['candidates'][0]['authors'] == records[0]['authors']


@pytest.mark.parametrize('has_pdf', [True, False])
def test_survey_import_completes_citation_before_export(client, monkeypatch, tmp_path, has_pdf):
    from app.ingestion.sources import FetchedPaper, parse_bibtex, parse_ris
    records = fake_records()[:1]
    if not has_pdf:
        records[0]['oa_pdf_url'] = None
    authors = [f'Family{i}, Given{i}' for i in range(15)]
    calls = []
    def metadata(doi):
        calls.append(doi)
        return FetchedPaper(source='crossref', doi=doi, title=records[0]['title'], authors=authors,
                            year=2026, venue='Published Journal', volume='56', issue='3', pages='958-973')
    @contextmanager
    def download(url, root, cancelled=None):
        yield fixture_pdf(tmp_path), {'url':url}
    install_search(monkeypatch, records)
    monkeypatch.setattr('app.ingestion.sources.fetch_crossref', metadata)
    monkeypatch.setattr('app.ingestion.pdf_download.download_pdf', download)
    created = create(client).json()
    state = wait_for(lambda: (lambda d: d if d['status'] == 'ready' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    cid = state['candidates'][0]['id']
    assert client.post(f"/api/literature/surveys/{created['id']}/import", json={'candidate_ids':[cid]}).status_code == 202
    finished = wait_for(lambda: (lambda d: d if d['import_status'] == 'done' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    result = finished['candidates'][0]
    assert result['status'] == ('imported' if has_pdf else 'imported_no_pdf')
    assert '引用信息已按出版记录补全' in result['note']
    for fmt, parse in [('bibtex',parse_bibtex), ('ris',parse_ris)]:
        exported = parse(client.get('/api/archive/export/'+fmt).text)[0]
        assert (exported.year, exported.volume, exported.issue) == (2026,'56','3')
        assert exported.authors == authors and exported.pages in {'958-973','958--973'}
    # An existing record may have been edited; duplicate selection cannot
    # replace it with current network metadata or request another lookup.
    pid = result['paper_id']
    client.patch(f'/api/papers/{pid}', json={'year':2024,'volume':'Chosen'})
    with Session(get_engine()) as session:
        candidate = session.get(LiteratureCandidate,cid)
        status, duplicate_id, _ = survey._import_one(session,candidate)
        paper = session.get(Paper,duplicate_id)
        assert status == 'duplicate' and paper.year == 2024 and paper.volume == 'Chosen'
    assert len(calls) == 1


def test_survey_uses_default_chat_model_for_expansion_and_screening(client, monkeypatch):
    with Session(get_engine()) as session:
        provider = Provider(name='Survey model', type='openai_compat', base_url='https://model.example.test')
        session.add(provider)
        session.commit()
        session.refresh(provider)
        session.add(Model(provider_id=provider.id, model_id='default-chat', role_default='chat'))
        session.commit()
    calls = []
    phrases = []

    def complete(ctx, prompt, ref_id):
        calls.append((ctx[2], ref_id))
        if '候选（JSON）' not in prompt:
            return ['full waveform inversion objective function']
        candidates = json.loads(prompt.split('候选（JSON）：', 1)[1].split('\n只输出', 1)[0])
        return [{'id': c['id'], 'keep': True, 'reason': '与目标函数主题相关'} for c in candidates]

    def search(session, phrase, from_year, per_page):
        phrases.append(phrase)
        return fake_records()

    monkeypatch.setattr(survey, '_complete_json', complete)
    monkeypatch.setattr(survey, '_search_phrase', search)
    monkeypatch.setattr(survey, 'SEARCH_PAUSE_SECONDS', 0)
    created = create(client, screen=True).json()
    detail = wait_for(lambda: (lambda d: d if d['status'] == 'ready' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    assert detail and detail['screened']
    assert [name for name, _ in calls] == ['default-chat', 'default-chat']
    assert 'full waveform inversion objective function' in phrases
    assert all(c['keep'] is True and c['relevance'] for c in detail['candidates'])


def test_import_selection_respects_cap_and_unknown(client, monkeypatch):
    install_search(monkeypatch)
    created = create(client).json()
    detail = wait_for(lambda: (lambda d: d if d['status'] == 'ready' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    ids = [c['id'] for c in detail['candidates']]
    too_many = client.post(f"/api/literature/surveys/{created['id']}/import",
                           json={'candidate_ids': [*ids, 99999]})
    assert too_many.status_code == 422
    unknown = client.post(f"/api/literature/surveys/{created['id']}/import", json={'candidate_ids': [424242]})
    assert unknown.status_code == 422


def test_import_marks_duplicate_metadata_and_pdf(client, monkeypatch, tmp_path):
    client.put('/api/settings/pdf_ingest_mode', json={'value': 'manual'}).raise_for_status()
    install_search(monkeypatch)
    # W3 duplicates an existing library paper by title.
    from app.ingestion.dedup import normalize_title

    with Session(get_engine()) as session:
        session.add(Paper(title='Existing library paper', source='manual',
                          title_norm=normalize_title('Existing library paper')))
        session.commit()
    created = create(client).json()
    detail = wait_for(lambda: (lambda d: d if d['status'] == 'ready' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    by_title = {c['title']: c for c in detail['candidates']}

    @contextmanager
    def fake_download(url, root, cancelled=None):
        yield fixture_pdf(tmp_path), {'url': url}

    monkeypatch.setattr('app.ingestion.pdf_download.download_pdf', fake_download)
    response = client.post(f"/api/literature/surveys/{created['id']}/import", json={
        'candidate_ids': [by_title['FWI objective functions 2025']['id'],
                          by_title['Robust inversion with noise']['id'],
                          by_title['Existing library paper']['id']]})
    assert response.status_code == 202

    def finished():
        state = client.get(f"/api/literature/surveys/{created['id']}").json()
        return state if state['import_status'] == 'done' and not state['counts'].get('queued_import') else None

    state = wait_for(finished)
    status_by_title = {c['title']: c['status'] for c in state['candidates']}
    assert status_by_title['FWI objective functions 2025'] == 'imported'
    assert status_by_title['Robust inversion with noise'] == 'imported_no_pdf'
    assert status_by_title['Existing library paper'] == 'duplicate'
    with Session(get_engine()) as session:
        papers = session.exec(select(Paper).where(Paper.title.contains('FWI objective'))).all()
        assert papers and papers[0].pdf_path and papers[0].full_text
        reading = session.exec(select(Paper).where(Paper.title == 'Existing library paper')).first()
        assert reading is not None
        indexed = set(session.exec(select(PaperChunk.paper_id)).all())
        assert indexed == {c['paper_id'] for c in state['candidates']}
        chunks = session.exec(select(PaperChunk).where(PaperChunk.paper_id == papers[0].id)).all()
        assert any('Open access full text about waveform inversion' in c.text for c in chunks)
    assert '保留检索题录' in next(c['note'] for c in state['candidates'] if c['status'] == 'imported')


def test_import_keeps_local_search_when_embedding_fails(client, monkeypatch, tmp_path):
    client.put('/api/settings/pdf_ingest_mode', json={'value': 'manual'}).raise_for_status()
    install_search(monkeypatch, records=fake_records()[:1])

    @contextmanager
    def download(url, root, cancelled=None):
        yield fixture_pdf(tmp_path), {'url': url}

    def embedding_unavailable(*args, **kwargs):
        raise RuntimeError('embedding unavailable')

    monkeypatch.setattr('app.ingestion.pdf_download.download_pdf', download)
    monkeypatch.setattr('app.rag.index.index_paper', embedding_unavailable)
    created = create(client).json()
    detail = wait_for(lambda: (lambda d: d if d['status'] == 'ready' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    assert client.post(f"/api/literature/surveys/{created['id']}/import", json={
        'candidate_ids': [detail['candidates'][0]['id']]}).status_code == 202
    state = wait_for(lambda: (lambda d: d if d['import_status'] == 'done' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    candidate = state['candidates'][0]
    assert candidate['status'] == 'imported'
    with Session(get_engine()) as session:
        paper = session.get(Paper, candidate['paper_id'])
        assert paper.pdf_path and paper.full_text
        from app.rag.scalable import lexical
        hits = lexical(session, 'waveform inversion', [paper.id], 6)
        assert any('Open access full text' in chunk.text for chunk, _ in hits)


def test_delete_survey_removes_candidates(client, monkeypatch):
    install_search(monkeypatch)
    created = create(client).json()
    wait_for(lambda: (lambda d: d if d['status'] == 'ready' else None)(
        client.get(f"/api/literature/surveys/{created['id']}").json()))
    assert client.delete(f"/api/literature/surveys/{created['id']}").status_code == 204
    with Session(get_engine()) as session:
        assert session.get(LiteratureSurvey, created['id']) is None
        assert not session.exec(select(LiteratureCandidate).where(
            LiteratureCandidate.survey_id == created['id'])).all()
