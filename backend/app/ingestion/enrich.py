"""Fill empty abstracts and bibliographic fields from public DOI sources."""
import json
from urllib.parse import quote

from sqlmodel import Session
from app.models import Paper
from app.models.base import utcnow

FIELDS = ('abstract', 'year', 'venue', 'volume', 'issue', 'pages')


def _fill_empty(paper: Paper, fetched) -> list[str]:
    """Copy only fields the paper is missing; never overwrite curated values."""
    filled = []
    for name in FIELDS:
        value = getattr(fetched, name, None)
        if value and not getattr(paper, name, None):
            setattr(paper, name, value)
            filled.append(name)
    if fetched.authors and not json.loads(paper.authors_json or '[]'):
        paper.authors_json = json.dumps(fetched.authors, ensure_ascii=False)
        filled.append('authors')
    return filled


def _openalex_abstract(session: Session, doi: str) -> str | None:
    """Best-effort abstract from OpenAlex's DOI lookup; network errors yield None."""
    from app.agent import openalex

    try:
        with openalex._client() as client:
            response = client.get(f'{openalex.BASE}/doi:{quote(doi)}', params=openalex._params(session, {}))
        if response.status_code != 200:
            return None
        return openalex._reconstruct_abstract(response.json(), limit=None) or None
    except Exception:
        return None


def enrich_paper(session: Session, paper: Paper) -> dict:
    """Complete one paper's empty metadata by DOI; never raises on lookup failures."""
    from app.ingestion.sources import lookup_doi_metadata, normalize_doi

    result = {'fields': [], 'abstract_source': None}
    doi = normalize_doi(paper.doi)
    if doi is None:
        return {**result, 'status': 'no_doi'}
    fetched, receipt = lookup_doi_metadata(doi)
    if fetched is None:
        return {**result, 'status': 'unavailable', 'error_type': (receipt or {}).get('error_type')}
    filled = _fill_empty(paper, fetched)
    abstract_source = 'crossref' if 'abstract' in filled else None
    if not paper.abstract:
        abstract = _openalex_abstract(session, doi)
        if abstract:
            paper.abstract = abstract
            filled.append('abstract')
            abstract_source = 'openalex'
    if not filled:
        return {**result, 'status': 'unchanged'}
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    if 'abstract' in filled:
        # Same refresh the import pipeline uses; unconfigured embeddings skip.
        try:
            from app.rag.index import index_local_paper, index_paper

            index_local_paper(session, paper)
            index_paper(session, paper)
        except Exception:
            session.rollback()
    return {**result, 'status': 'updated', 'fields': filled, 'abstract_source': abstract_source}
