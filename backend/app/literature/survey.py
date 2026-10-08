"""Literature survey: search public sources, screen with the chat model, import on selection.

Flow per survey (worker thread):
1. Optional query expansion — the scholarly corpus is mostly English, so the
   configured chat model turns the user's topic into up to 3 search phrases.
   Without a model the original query is used as-is.
2. OpenAlex search per phrase (public API, 1s between
   calls), filtered to the requested year window; merge and dedupe.
3. Optional one-shot LLM screening marks candidates keep/reason — a
   suggestion for the human, never an import decision.
4. The user reviews the list and selects; ``start_import`` then runs serially
   with pacing. Downloads use public OA URLs only; no institutional proxy or
   shared-account automation (rate-control lesson from InstSci, MIT-licensed,
   design reference only). Subscription-only papers import metadata-only and
   the user can attach a PDF manually later.
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from threading import RLock

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.config import get_settings
from app.models import LiteratureCandidate, LiteratureSurvey, Paper, PaperChunk, PaperReadingState
from app.models.literature import _now

_log = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='literature')
_lock = RLock()
_active_surveys: set[int] = set()
_active_imports: set[int] = set()

IMPORT_BATCH_CAP = 10
DOWNLOAD_PAUSE_SECONDS = 3.0
SEARCH_PAUSE_SECONDS = 1.0
MAX_PHRASES = 3
PER_PHRASE_PAGE = 25


# ---------------------------------------------------------------- snapshots

def survey_summary(row: LiteratureSurvey) -> dict:
    return {
        'id': row.id, 'query': row.query, 'years': row.years, 'max_results': row.max_results,
        'status': row.status, 'error': row.error, 'screened': row.screened,
        'import_status': row.import_status,
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'finished_at': row.finished_at.isoformat() if row.finished_at else None,
    }


def candidate_summary(row: LiteratureCandidate) -> dict:
    try:
        authors = json.loads(row.authors_json)
    except ValueError:
        authors = []
    return {
        'id': row.id, 'survey_id': row.survey_id, 'openalex_id': row.openalex_id,
        'doi': row.doi, 'arxiv_id': row.arxiv_id, 'title': row.title, 'year': row.year,
        'venue': row.venue, 'authors': authors, 'cited_by_count': row.cited_by_count,
        'oa_pdf_url': row.oa_pdf_url or None, 'abstract': row.abstract,
        'relevance': row.relevance, 'keep': row.keep, 'status': row.status,
        'paper_id': row.paper_id, 'note': row.note,
    }


def _recover(session: Session, survey_id: int) -> None:
    """A status read is the recovery point after a restart (documents.py pattern)."""
    row = session.get(LiteratureSurvey, survey_id)
    if row and row.status in {'queued', 'running'} and survey_id not in _active_surveys:
        row.status = 'interrupted'
        row.error = '调研在完成前被中断，可重新发起。'
        session.add(row)
    if row and row.import_status == 'running' and survey_id not in _active_imports:
        row.import_status = 'idle'
        session.add(row)
        for candidate in session.exec(select(LiteratureCandidate).where(
                LiteratureCandidate.survey_id == survey_id,
                LiteratureCandidate.status == 'queued_import')).all():
            candidate.status = 'candidate'
            session.add(candidate)
    session.commit()


def detail(session: Session, survey_id: int) -> dict:
    row = session.get(LiteratureSurvey, survey_id)
    if row is None:
        raise HTTPException(404, '调研任务不存在。')
    with _lock:
        session.expire_all()
        _recover(session, survey_id)
        candidates = session.exec(select(LiteratureCandidate).where(
            LiteratureCandidate.survey_id == survey_id).order_by(LiteratureCandidate.id)).all()
        counts: dict[str, int] = {}
        for candidate in candidates:
            counts[candidate.status] = counts.get(candidate.status, 0) + 1
        return {**survey_summary(row), 'candidates': [candidate_summary(c) for c in candidates],
                'counts': counts, 'import_batch_cap': IMPORT_BATCH_CAP}


def list_surveys(session: Session, limit: int = 30) -> list[dict]:
    with _lock:
        rows = session.exec(select(LiteratureSurvey).order_by(
            LiteratureSurvey.id.desc()).limit(limit)).all()
        for row in rows:
            _recover(session, row.id)
        session.expire_all()
        rows = session.exec(select(LiteratureSurvey).order_by(
            LiteratureSurvey.id.desc()).limit(limit)).all()
        return [survey_summary(row) for row in rows]


# ---------------------------------------------------------------- survey run

def start_survey(session: Session, query: str, years: int, max_results: int, screen: bool) -> dict:
    query = (query or '').strip()
    if not query:
        raise HTTPException(422, '请先描述要调研的主题。')
    row = LiteratureSurvey(query=query[:500], years=years, max_results=max_results, screened=False)
    row.status = 'queued'
    session.add(row)
    session.commit()
    session.refresh(row)
    engine = session.get_bind()
    with _lock:
        _active_surveys.add(row.id)
        try:
            _pool.submit(copy_context().run, _run_survey, engine, row.id, screen)
        except Exception:
            _active_surveys.discard(row.id)
            row.status, row.error = 'error', '无法启动调研任务，请重试。'
            session.add(row)
            session.commit()
            raise
    return survey_summary(row)


def _chat_context(session: Session):
    from app.providers.selection import pick_llm

    try:
        return pick_llm(session, 'chat')
    except Exception:
        return None


def _complete_json(ctx, prompt: str, ref_id: str):
    client, provider, model = ctx
    result = client.complete(provider, model, [{'role': 'user', 'content': prompt}],
                             request_kind='chat', ref_id=ref_id, max_tokens=2000)
    text = (result.content or '').strip()
    match = re.search(r'\[.*\]', text, re.S)
    if not match:
        raise ValueError('model did not return a JSON list')
    return json.loads(match.group(0))


def _expand(ctx, query: str, survey_id: int) -> list[str]:
    if ctx is None:
        return [query]
    prompt = (
        '你是学术检索助手。把用户的研究主题改写成最多3条用于 OpenAlex 检索的英文短语，'
        '覆盖主题的不同表述。只输出 JSON 字符串数组，不要解释。\n'
        f'主题：{query}'
    )
    try:
        phrases = [str(p).strip() for p in _complete_json(ctx, prompt, f'literature-{survey_id}') if str(p).strip()]
    except Exception:
        return [query]
    phrases = phrases[:MAX_PHRASES]
    return list(dict.fromkeys([query, *phrases]))[:MAX_PHRASES] or [query]


def _search_phrase(session: Session, phrase: str, from_year: int, per_page: int) -> list[dict]:
    from app.agent.openalex import BASE, _client, _params, _record

    with _client() as client:
        response = client.get(BASE, params=_params(session, {
            'search': phrase,
            'filter': f'from_publication_date:{from_year}-01-01',
            'per-page': per_page,
        }))
        if response.status_code in {429, 503}:
            # Retry temporary 429/503 responses with a bounded wait. This
            # is a background job, so one bounded wait-and-retry is cheaper for
            # the user than failing the whole survey (InstSci does the same).
            try:
                wait = min(max(float(response.headers.get('retry-after', '30')), 1.0), 60.0)
            except ValueError:
                wait = 30.0
            time.sleep(wait)
            response = client.get(BASE, params=_params(session, {
                'search': phrase,
                'filter': f'from_publication_date:{from_year}-01-01',
                'per-page': per_page,
            }))
        if response.status_code == 429:
            raise RuntimeError('OpenAlex 请求受到限流，请稍后重试。')
        if response.status_code != 200:
            raise RuntimeError(f'OpenAlex HTTP {response.status_code}')
    return [_record(work, full_authors=True) for work in response.json().get('results', []) if isinstance(work, dict)]


def _screen(ctx, query: str, candidates: list[dict], survey_id: int) -> dict[int, dict]:
    prompt = (
        '你是文献筛选助手。根据研究主题判断每篇候选文献是否值得研究者细看。\n'
        f'主题：{query}\n候选（JSON）：' + json.dumps(
            [{'id': c['id'], 'title': c['title'], 'year': c['year'], 'venue': c['venue'],
              'cited_by_count': c['cited_by_count'],
              'abstract': c['abstract'][:300]} for c in candidates], ensure_ascii=False) +
        '\n只输出 JSON 数组，每项 {"id": 候选id, "keep": true/false, "reason": "不超过40字的中文理由"}。'
        '宁多勿漏：主题相关即 keep=true。'
    )
    try:
        rows = _complete_json(ctx, prompt, f'literature-{survey_id}')
    except Exception:
        return {}
    verdicts: dict[int, dict] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get('id'), int):
            verdicts[row['id']] = {'keep': bool(row.get('keep')), 'reason': str(row.get('reason', ''))[:120]}
    return verdicts


def _run_survey(engine, survey_id: int, screen: bool) -> None:
    try:
        with Session(engine) as session:
            row = session.get(LiteratureSurvey, survey_id)
            if row is None:
                return
            row.status = 'running'
            session.add(row)
            session.commit()
            query, years, cap = row.query, row.years, row.max_results
            ctx = _chat_context(session) if screen else None

            phrases = _expand(ctx, query, survey_id)
            from_year = max(1900, _now().year - max(0, years - 1))
            merged: list[dict] = []
            seen: set[str] = set()
            for index, phrase in enumerate(phrases):
                if index:
                    time.sleep(SEARCH_PAUSE_SECONDS)
                for record in _search_phrase(session, phrase, from_year, PER_PHRASE_PAGE):
                    key = record.get('openalex_id') or record.get('doi') or record.get('title', '')
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    merged.append(record)
            if not merged:
                raise RuntimeError('没有检索到文献，可调整主题或时间范围后重试。')
            merged = merged[:cap]

            candidates = [
                LiteratureCandidate(
                    survey_id=survey_id, openalex_id=item.get('openalex_id', ''),
                    doi=item.get('doi', ''), arxiv_id=_arxiv_id(item),
                    title=item.get('title', '')[:500], year=item.get('year'),
                    venue=item.get('venue', ''),
                    authors_json=json.dumps(item.get('authors', []), ensure_ascii=False),
                    cited_by_count=item.get('cited_by_count', 0) or 0,
                    oa_pdf_url=item.get('oa_pdf_url') or '',
                    abstract=item.get('text', '')[:2000])
                for item in merged
            ]
            session.add_all(candidates)
            session.commit()
            session.refresh(row)
            screened = False
            if ctx is not None:
                verdicts = _screen(ctx, query, [candidate_summary(c) for c in candidates], survey_id)
                for candidate in candidates:
                    verdict = verdicts.get(candidate.id)
                    if verdict is not None:
                        candidate.keep, candidate.relevance = verdict['keep'], verdict['reason']
                screened = bool(verdicts)
            row.expansion_used = json.dumps(phrases, ensure_ascii=False)
            row.screened = screened
            row.status, row.error, row.finished_at = 'ready', '', _now()
            session.add(row)
            session.add_all(candidates)
            session.commit()
    except Exception as exc:
        _log.warning('literature survey failed: survey=%s type=%s', survey_id, type(exc).__name__)
        try:
            with Session(engine) as session:
                row = session.get(LiteratureSurvey, survey_id)
                if row is not None and row.status in {'queued', 'running'}:
                    row.status, row.error, row.finished_at = 'error', str(exc)[:500], _now()
                    session.add(row)
                    session.commit()
        except Exception:
            _log.warning('could not record survey failure', exc_info=True)
    finally:
        with _lock:
            _active_surveys.discard(survey_id)


def _arxiv_id(item: dict) -> str:
    for value in (item.get('doi') or '', item.get('oa_pdf_url') or ''):
        match = re.search(r'arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}|[a-z-]+\.[A-Z]{2}/[0-9]{7})', value, re.I)
        if match:
            return match.group(1)
    return ''


# ---------------------------------------------------------------- import run

def start_import(session: Session, survey_id: int, candidate_ids: list[int]) -> dict:
    row = session.get(LiteratureSurvey, survey_id)
    if row is None:
        raise HTTPException(404, '调研任务不存在。')
    if row.status != 'ready':
        raise HTTPException(409, '调研尚未完成，暂不能导入。')
    ids = list(dict.fromkeys(int(i) for i in candidate_ids if isinstance(i, int) and not isinstance(i, bool)))
    if not ids:
        raise HTTPException(422, '请先选择要添加的文献。')
    if len(ids) > IMPORT_BATCH_CAP:
        raise HTTPException(422, f'单次最多添加 {IMPORT_BATCH_CAP} 篇，请分批添加。')
    with _lock:
        if survey_id in _active_imports:
            raise HTTPException(409, '该调研已有导入任务执行中，请稍候。')
        session.expire_all()
        candidates = session.exec(select(LiteratureCandidate).where(
            LiteratureCandidate.id.in_(ids),
            LiteratureCandidate.survey_id == survey_id)).all()
        selectable = {c.id for c in candidates if c.status in {'candidate', 'failed'}}
        unknown = set(ids) - selectable
        if unknown:
            raise HTTPException(422, '所选文献不可导入（可能已添加或正在导入）。')
        for candidate in candidates:
            candidate.status = 'queued_import'
            candidate.note = ''
            session.add(candidate)
        row.import_status = 'running'
        session.add(row)
        session.commit()
        engine = session.get_bind()
        _active_imports.add(survey_id)
        try:
            _pool.submit(copy_context().run, _run_import, engine, survey_id)
        except Exception:
            _active_imports.discard(survey_id)
            row.import_status = 'idle'
            session.add(row)
            session.commit()
            raise
    return {'queued': len(ids), 'import_batch_cap': IMPORT_BATCH_CAP}


def _queue_reading(session: Session, paper_id: int) -> None:
    state = session.exec(select(PaperReadingState).where(
        PaperReadingState.paper_id == paper_id)).first()
    if state is None:
        session.add(PaperReadingState(paper_id=paper_id, status='queued'))
    elif state.status == 'unread':
        state.status = 'queued'
        session.add(state)


def _index_imported(session: Session, paper: Paper) -> str:
    from app.ingestion.document_pipeline import waiting_for_markdown
    if waiting_for_markdown(session, paper):
        return 'PDF 已保存；OCR 与 Markdown 在后台处理，完成后自动建立全文索引。可在论文详情查看进度。'
    from app.rag.index import index_local_paper, index_paper

    index_local_paper(session, paper)
    try:
        index_paper(session, paper)
    except Exception as exc:
        session.rollback()
        _log.warning('Survey paper retained with local search; embedding unavailable (%s)', type(exc).__name__)
        return '已保存，可先关键词查找；语义索引暂未完成。'
    return ''


def _import_one(session: Session, candidate: LiteratureCandidate) -> tuple[str, int | None, str]:
    """Import a single candidate; returns (status, paper_id, note)."""
    from app.ingestion.pdf_download import download_pdf
    from app.ingestion.service import find_duplicate, persist_fetched
    from app.ingestion.sources import FetchedPaper, fetch_arxiv, lookup_doi_metadata

    root = Path(get_settings().data_dir)
    duplicate = find_duplicate(session, candidate.doi or None, candidate.arxiv_id or None, candidate.title)
    if duplicate is not None:
        note = ''
        if session.exec(select(PaperChunk.id).where(PaperChunk.paper_id == duplicate.id).limit(1)).first() is None:
            note = _index_imported(session, duplicate)
        _queue_reading(session, duplicate.id)
        return 'duplicate', duplicate.id, '库中已有此文，已标记待读。' + note

    fetched: FetchedPaper | None = None
    source_url = ''
    if candidate.arxiv_id:
        try:
            fetched = fetch_arxiv(candidate.arxiv_id)
            source_url = f'https://arxiv.org/abs/{candidate.arxiv_id}'
        except Exception as exc:
            _log.warning('survey arxiv fetch failed type=%s', type(exc).__name__)
            fetched = None
    if fetched is None and candidate.oa_pdf_url:
        fetched = FetchedPaper(source='public_pdf', source_ref=candidate.oa_pdf_url,
                               title=candidate.title, doi=candidate.doi or None,
                               authors=json.loads(candidate.authors_json) if candidate.authors_json else [],
                               abstract=candidate.abstract or None, year=candidate.year,
                               venue=candidate.venue or None)
        source_url = candidate.oa_pdf_url
    if fetched is None:
        fetched = FetchedPaper(source='manual', title=candidate.title,
                               doi=candidate.doi or None, arxiv_id=candidate.arxiv_id or None,
                               authors=json.loads(candidate.authors_json) if candidate.authors_json else [],
                               abstract=candidate.abstract or None, year=candidate.year,
                               venue=candidate.venue or None)
        source_url = ''

    citation_note = ''
    if fetched.source in {'public_pdf', 'manual'}:
        verified, metadata = lookup_doi_metadata(candidate.doi or None)
        if verified is not None:
            if verified.authors:
                fetched.authors = verified.authors
            for field in ('year', 'venue', 'volume', 'issue', 'pages'):
                value = getattr(verified, field)
                if value:
                    setattr(fetched, field, value)
            citation_note = '引用信息已按出版记录补全。'
        elif metadata is not None:
            citation_note = '引用信息补全暂不可用，已保留检索题录。'

    try:
        if source_url and candidate.arxiv_id == '' and fetched.source == 'public_pdf':
            with download_pdf(source_url, root) as (path, _receipt):
                fetched.pdf_file = path
                paper = persist_fetched(session, fetched, root / 'pdfs')
        else:
            paper = persist_fetched(session, fetched, root / 'pdfs')
    except Exception as exc:
        session.rollback()
        return 'failed', None, f'导入失败：{type(exc).__name__}'

    index_note = _index_imported(session, paper)
    _queue_reading(session, paper.id)
    has_pdf = bool(paper.pdf_path)
    return ('imported' if has_pdf else 'imported_no_pdf'), paper.id, (
        ('' if has_pdf else '未找到公开 PDF，已保存题录；可稍后手动补充原文。') + citation_note + index_note)


def _run_import(engine, survey_id: int) -> None:
    try:
        while True:
            with Session(engine) as session:
                candidate = session.exec(select(LiteratureCandidate).where(
                    LiteratureCandidate.survey_id == survey_id,
                    LiteratureCandidate.status == 'queued_import').order_by(
                    LiteratureCandidate.id)).first()
                if candidate is None:
                    row = session.get(LiteratureSurvey, survey_id)
                    if row is not None:
                        row.import_status = 'done'
                        session.add(row)
                        session.commit()
                    return
                status, paper_id, note = _import_one(session, candidate)
                candidate.status, candidate.paper_id, candidate.note = status, paper_id, note
                session.add(candidate)
                session.commit()
                downloaded = status == 'imported'
            # Public-API pacing: serial imports with a pause after each PDF
            # download (InstSci rate-control lesson; see docs/literature-survey.md).
            time.sleep(DOWNLOAD_PAUSE_SECONDS if downloaded else 0.2)
    except Exception:
        _log.warning('literature import failed', exc_info=True)
        try:
            with Session(engine) as session:
                row = session.get(LiteratureSurvey, survey_id)
                if row is not None:
                    row.import_status = 'idle'
                    session.add(row)
                for candidate in session.exec(select(LiteratureCandidate).where(
                        LiteratureCandidate.survey_id == survey_id,
                        LiteratureCandidate.status == 'queued_import')).all():
                    candidate.status, candidate.note = 'failed', '导入中断，可重试。'
                    session.add(candidate)
                session.commit()
        except Exception:
            _log.warning('could not record import failure', exc_info=True)
    finally:
        with _lock:
            _active_imports.discard(survey_id)


def delete_survey(session: Session, survey_id: int) -> None:
    row = session.get(LiteratureSurvey, survey_id)
    if row is None:
        raise HTTPException(404, '调研任务不存在。')
    with _lock:
        if survey_id in _active_surveys or survey_id in _active_imports:
            raise HTTPException(409, '该调研正在执行，请等待完成后再删除。')
        for candidate in session.exec(select(LiteratureCandidate).where(
                LiteratureCandidate.survey_id == survey_id)).all():
            session.delete(candidate)
        session.delete(row)
        session.commit()
