"""OpenAlex scholarly search as chat-agent tools.

OpenAlex offers keyless basic use of its scholarly metadata API; a free API
key raises the daily budget. These tools return compact work records
so the agent can look beyond the local library, verify bibliographic facts
and hand open-access PDF URLs to ``import_paper_pdf``. They reuse the
existing web-source provenance shape (``type: 'web'`` rows with url + text)
so results are recorded like other web evidence.

Design reference: PaperSpark's OpenAlex toolset (idea only, CC BY-NC) — in
particular exposing the scholarly API directly to the conversation agent
instead of a separate search page. Implementation and record shape are
PaperMind's own.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import httpx

from app.models import Setting

BASE = 'https://api.openalex.org/works'
MAILTO_SETTING = 'openalex_mailto'
USER_AGENT = 'PaperMind research reader'
TIMEOUT = httpx.Timeout(30, connect=10)


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={'User-Agent': USER_AGENT}, follow_redirects=True)


def _params(session, extra: dict) -> dict:
    params = dict(extra)
    row = session.get(Setting, MAILTO_SETTING)
    mailto = (row.value or '').strip() if row else ''
    if mailto:
        params['mailto'] = mailto
    return params


def _reconstruct_abstract(work: dict) -> str:
    inverted = work.get('abstract_inverted_index')
    if not isinstance(inverted, dict) or not inverted:
        return ''
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        if isinstance(word, str) and isinstance(indexes, list):
            positions.extend((index, word) for index in indexes if isinstance(index, int))
    return ' '.join(word for _, word in sorted(positions))[:1200]


def _record(work: dict, *, full_authors: bool = False) -> dict:
    """Compact a Work JSON into an agent-readable record with provenance fields."""
    title = (work.get('display_name') or '').strip()
    year = work.get('publication_year')
    doi = work.get('doi') or ''
    primary = work.get('primary_location') or {}
    source = primary.get('source') or {}
    venue = source.get('display_name') or ''
    authors = [
        author['author']['display_name']
        for author in (work.get('authorships', []) if full_authors else work.get('authorships', [])[:6])
        if isinstance(author, dict) and isinstance(author.get('author'), dict) and author['author'].get('display_name')
    ]
    best_oa = work.get('best_oa_location') or {}
    pdf_url = best_oa.get('pdf_url') or ''
    oa_url = pdf_url or best_oa.get('landing_page_url') or ''
    landing = work.get('id') or ''
    url = oa_url or doi or landing
    abstract = _reconstruct_abstract(work)
    record = {
        'type': 'web',
        'url': url,
        'openalex_id': (landing.rsplit('/', 1)[-1] if landing else ''),
        'title': title,
        'year': year,
        'authors': authors,
        'venue': venue,
        'doi': doi.replace('https://doi.org/', '') if isinstance(doi, str) else '',
        'cited_by_count': work.get('cited_by_count', 0),
        'is_oa': bool(work.get('open_access', {}).get('is_oa')),
        'oa_pdf_url': pdf_url or None,
    }
    # web provenance requires non-empty url + text; fall back to a one-line
    # description when no abstract is indexed.
    record['text'] = abstract or (f'{title}（{venue}，{year}）' if title else '')
    return record


def _error(message: str) -> str:
    return json.dumps({'error': message, 'error_type': 'openalex'}, ensure_ascii=False)


def search_openalex(session, query, limit=8):
    query = (query or '').strip()
    if not query:
        return _error('empty query')
    limit = max(1, min(int(limit or 8), 25))
    try:
        with _client() as client:
            response = client.get(BASE, params=_params(session, {'search': query, 'per-page': limit}))
        if response.status_code != 200:
            return _error(f'OpenAlex HTTP {response.status_code}')
        payload = response.json()
        works = payload.get('results', [])
        records = [_record(work) for work in works if isinstance(work, dict)]
        if not records:
            return json.dumps({'note': 'OpenAlex 没有返回结果，可调整关键词重试或改用 search_web。'}, ensure_ascii=False)
        return json.dumps(records, ensure_ascii=False)
    except httpx.HTTPError:
        return _error('network error')


def find_related_openalex(session, doi=None, openalex_id=None, limit=8):
    """Works related to one paper, via OpenAlex ``related_works``."""
    limit = max(1, min(int(limit or 8), 25))
    identifier = ''
    if openalex_id:
        identifier = f'{BASE}/{quote(str(openalex_id).strip())}'
    elif doi:
        identifier = f'{BASE}/doi:{quote(str(doi).strip().removeprefix("https://doi.org/"))}'
    if not identifier:
        return _error('doi or openalex_id required')
    try:
        with _client() as client:
            response = client.get(identifier, params=_params(session, {}))
        if response.status_code != 200:
            return _error(f'OpenAlex HTTP {response.status_code}')
        related = response.json().get('related_works') or []
        ids = [str(url).rsplit('/', 1)[-1] for url in related[:limit] if url]
        if not ids:
            return json.dumps({'note': '该文献在 OpenAlex 没有关联工作记录。'}, ensure_ascii=False)
        with _client() as client:
            response = client.get(BASE, params=_params(session, {'filter': 'openalex_id:' + '|'.join(ids), 'per-page': len(ids)}))
        if response.status_code != 200:
            return _error(f'OpenAlex HTTP {response.status_code}')
        works = response.json().get('results', [])
        records = [_record(work) for work in works if isinstance(work, dict)]
        if not records:
            return json.dumps({'note': '关联工作暂无详细元数据。'}, ensure_ascii=False)
        return json.dumps(records, ensure_ascii=False)
    except httpx.HTTPError:
        return _error('network error')
