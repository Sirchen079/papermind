import json

from sqlmodel import Session

from app.db.engine import get_engine
from app.ingestion.enrich import enrich_paper
from app.ingestion.sources import FetchedPaper, strip_jats
from app.models import Paper


def _add_paper(**kwargs):
    with Session(get_engine()) as s:
        paper = Paper(source='manual', title='DOI enrichment fixture', **kwargs)
        s.add(paper)
        s.commit()
        s.refresh(paper)
        pid = paper.id
    return pid


def test_strip_jats_removes_title_tags_and_entities():
    assert strip_jats('<jats:title>Abstract</jats:title><jats:p>A &amp; B</jats:p>') == 'A & B'
    assert strip_jats('<jats:p>Caf&eacute; &lt;x&gt;</jats:p>') == 'Café <x>'


def test_strip_jats_empty_or_tag_only_input_returns_none():
    assert strip_jats(None) is None
    assert strip_jats('') is None
    assert strip_jats('   ') is None
    assert strip_jats('<jats:p>  </jats:p>') is None


def test_crossref_abstract_and_fields_fill_empty_slots(client, monkeypatch):
    fetched = FetchedPaper(source='crossref', doi='10.1000/x', title='Looked up', abstract='Crossref abstract',
                           authors=['Doe, Jane'], year=2020, venue='Journal', volume='7', issue='2', pages='1--9')
    monkeypatch.setattr('app.ingestion.sources.lookup_doi_metadata', lambda doi: (fetched, {'status': 'retrieved'}))
    pid = _add_paper(doi='10.1000/x')
    with Session(get_engine()) as s:
        paper = s.get(Paper, pid)
        result = enrich_paper(s, paper)
        assert result['status'] == 'updated'
        assert result['abstract_source'] == 'crossref'
        assert 'abstract' in result['fields'] and 'authors' in result['fields']
        assert paper.abstract == 'Crossref abstract'
        assert json.loads(paper.authors_json) == ['Doe, Jane']
        assert paper.year == 2020 and paper.venue == 'Journal'
        assert paper.volume == '7' and paper.issue == '2' and paper.pages == '1--9'
        assert paper.updated_at is not None


def test_openalex_abstract_used_untruncated_when_crossref_has_none(client, monkeypatch):
    fetched = FetchedPaper(source='crossref', doi='10.1000/x', title='Looked up')
    monkeypatch.setattr('app.ingestion.sources.lookup_doi_metadata', lambda doi: (fetched, {'status': 'retrieved'}))
    words = [f'word{i:04d}' for i in range(300)]
    inverted = {word: [i] for i, word in enumerate(words)}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {'abstract_inverted_index': inverted}

    class FakeClient:
        def __init__(self):
            self.urls = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None):
            self.urls.append(url)
            return FakeResponse()

    fake = FakeClient()
    monkeypatch.setattr('app.agent.openalex._client', lambda: fake)
    pid = _add_paper(doi='10.1000/x')
    with Session(get_engine()) as s:
        paper = s.get(Paper, pid)
        result = enrich_paper(s, paper)
        assert result['status'] == 'updated' and result['abstract_source'] == 'openalex'
        assert len(paper.abstract) > 1200
        assert paper.abstract.startswith('word0000') and paper.abstract.endswith('word0299')
    assert fake.urls == ['https://api.openalex.org/works/doi:10.1000/x']


def test_existing_values_are_never_overwritten(client, monkeypatch):
    fetched = FetchedPaper(source='crossref', doi='10.1000/x', title='Looked up', abstract='New abstract',
                           authors=['Doe, Jane'], year=1999, venue='New venue')
    monkeypatch.setattr('app.ingestion.sources.lookup_doi_metadata', lambda doi: (fetched, {'status': 'retrieved'}))
    pid = _add_paper(doi='10.1000/x', abstract='Original abstract', authors_json=json.dumps(['Keep, Me']), year=2001, venue='Old venue')
    with Session(get_engine()) as s:
        paper = s.get(Paper, pid)
        result = enrich_paper(s, paper)
        assert result['status'] == 'unchanged' and result['fields'] == []
        assert result['abstract_source'] is None
        assert paper.abstract == 'Original abstract'
        assert json.loads(paper.authors_json) == ['Keep, Me']
        assert paper.year == 2001 and paper.venue == 'Old venue'


def test_crossref_network_failure_returns_unavailable(client, monkeypatch):
    monkeypatch.setattr('app.ingestion.sources.lookup_doi_metadata',
                        lambda doi: (None, {'status': 'unavailable', 'error_type': 'HTTPError'}))
    pid = _add_paper(doi='10.1000/x')
    with Session(get_engine()) as s:
        paper = s.get(Paper, pid)
        result = enrich_paper(s, paper)
        assert result['status'] == 'unavailable'
        assert result['error_type'] == 'HTTPError'
        assert paper.abstract is None


def test_enrich_api_rejects_more_than_200_ids(client):
    res = client.post('/api/papers/enrich-metadata', json={'paper_ids': list(range(1, 202))})
    assert res.status_code == 422


def test_enrich_api_returns_results_and_counts(client, monkeypatch):
    monkeypatch.setattr('app.ingestion.sources.lookup_doi_metadata',
                        lambda doi: (None, {'status': 'unavailable', 'error_type': 'HTTPError'}))
    with Session(get_engine()) as s:
        with_doi = Paper(source='manual', title='Has DOI', doi='10.1000/a')
        without_doi = Paper(source='manual', title='No DOI')
        s.add(with_doi)
        s.add(without_doi)
        s.commit()
        s.refresh(with_doi)
        s.refresh(without_doi)
        ids = [with_doi.id, without_doi.id]
    res = client.post('/api/papers/enrich-metadata', json={'paper_ids': ids})
    assert res.status_code == 200
    body = res.json()
    assert body['counts'] == {'unavailable': 1, 'no_doi': 1}
    assert [r['paper_id'] for r in body['results']] == ids
    assert body['results'][0]['error_type'] == 'HTTPError'
