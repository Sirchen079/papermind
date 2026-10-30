"""Local institution preferences and verified attachment to an existing paper."""
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock, RLock
import time
from uuid import uuid4

import pymupdf
from app.ingestion import institutional_runtime as runtime
from app.ingestion.dedup import normalize_title
from app.ingestion.sources import FetchedPaper, normalize_doi
from app.models import Paper

_browser_lock = Lock()
_json_lock = RLock()


def _config_path():
    return Path(os.environ.get('PAPERMIND_INSTITUTION_CONFIG') or runtime.root() / 'config.json')


def config():
    try:
        data = json.loads(_config_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    return {key: str(data.get(key) or '') for key in ('institution', 'aliases', 'library_url')}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with _json_lock:
            for attempt in range(8):
                try:
                    temp.replace(path)
                    break
                except PermissionError:
                    if attempt == 7:
                        raise
                    time.sleep(.02)
    finally:
        temp.unlink(missing_ok=True)


def configure(institution, library_url='', aliases=''):
    from app.security.url_guard import ensure_http_url
    if not institution.strip() or len(institution) > 200 or len(aliases) > 500:
        raise ValueError('请填写学校或机构名称（最多 200 字）。')
    if library_url:
        ensure_http_url(library_url)
        from urllib.parse import urlsplit
        if urlsplit(library_url).username or urlsplit(library_url).password:
            raise ValueError('图书馆入口不能包含账号或密码。')
    write_json(_config_path(), dict(institution=institution.strip(), aliases=aliases.strip(), library_url=library_url.strip()))
    return config()


def attach(session, paper_id, item, folder, expected, *, access_mode='institutional_browser'):
    from app.config import get_settings
    from app.ingestion.service import persist_fetched
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        return 'not_found'
    if paper.pdf_path:
        return 'has_pdf'
    if normalize_doi(paper.doi) != normalize_doi(expected.get('doi')) or paper.title != expected.get('title'):
        return 'identity_changed'
    doi = normalize_doi(paper.doi)
    if item.get('status') != 'success' or item.get('verified_match') is not True:
        return 'unverified'
    if doi and normalize_doi(item.get('doi')) != doi:
        return 'unverified'
    path = Path(item.get('pdf_path') or '').resolve()
    try:
        path.relative_to(folder.resolve())
    except ValueError:
        return 'invalid_pdf'
    if not path.is_file() or path.stat().st_size > 100 * 1024 * 1024:
        return 'invalid_pdf'
    with path.open('rb') as source:
        if not source.read(1024).startswith(b'%PDF-'):
            return 'invalid_pdf'
    # Independent identity check: a DOI occurring only in references is insufficient.
    from app.ingestion.pdf_identify import extract_candidates, _title_area_match
    with pymupdf.open(path) as doc:
        if not doc.page_count:
            return 'invalid_pdf'
        candidates = extract_candidates(doc[0].get_text(), doc.metadata)
    if any(line.strip().lower().startswith(('supplementary information', 'supplementary material',
               'supporting information', 'electronic supporting', '补充材料'))
           for line in candidates['text'].splitlines()[:10]):
        return 'unverified'
    own_doi = any(normalize_doi(c['doi']) == doi and c['kind'] != 'reference'
                  for c in candidates['doi_candidates']) if doi else False
    if not own_doi and not _title_area_match(candidates['text'], normalize_title(paper.title)):
        return 'unverified'
    root = Path(get_settings().data_dir)
    # Empty fields preserve all curated metadata on the explicitly chosen target.
    fetched = FetchedPaper(source='institutional_pdf', pdf_file=path)
    paper = persist_fetched(session, fetched, root / 'pdfs', target_paper_id=paper_id)
    from app.literature.survey import _index_imported
    _index_imported(session, paper)
    receipt = {'access_mode': access_mode, 'doi': doi,
               'retrieved_at': datetime.now(timezone.utc).isoformat(),
               'source_url': 'https://doi.org/' + doi if doi else config()['library_url'],
               'engine_revision': runtime.REVISION, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    stored = Path(paper.pdf_path)
    write_json(stored.with_suffix('.source.json'), receipt)
    return 'attached'
