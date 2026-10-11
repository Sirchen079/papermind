"""Read saved review artifacts for a research conversation.

``get_paper_card`` returns one paper's structured reading card: field values
with their verbatim quotes, verification status and PDF pages. The card rows
are written by ``app.reviews.cards`` during review and literature-map runs.

``read_literature_map`` returns a review's generated map, reusing
``app.reviews.map.detail_map`` so the assistant sees the same themes,
syntheses and assignments as the review pages. Long lists are paged with
``next_offset``, following the read tools' existing conventions.
"""
from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from app.models import Paper
from app.models.base import utc_iso
from app.models.card import PaperCard
from app.models.review import LibraryReview, ReviewPaper

CARD_FIELDS = ('problem', 'mechanism', 'data_setting', 'boundary')
# Page sizes keep one result within the usual tool output budget; a theme
# synthesis is a few kilobytes, one paper's key fields a few hundred characters.
THEMES_PER_PAGE = 3
PAPERS_PER_PAGE = 10
OVERVIEW_THEME_PAPERS = 20


def _review_brief(row: LibraryReview) -> dict[str, Any]:
    return {'review_id': row.id, 'title': row.question}


def _verification_summary(card: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    fields = [card.get(name) for name in CARD_FIELDS] + list(card.get('contributions') or [])
    for field in fields:
        status = field.get('status') if isinstance(field, dict) else None
        if isinstance(status, str) and status:
            counts[status] = counts.get(status, 0) + 1
    return counts


def _member_reviews(session: Session, paper_id: int) -> list[LibraryReview]:
    """Reviews containing this paper, most recently updated first."""
    memberships = session.exec(select(ReviewPaper).where(ReviewPaper.paper_id == paper_id)).all()
    review_ids = list(dict.fromkeys(m.review_id for m in memberships))
    if not review_ids:
        return []
    rows = session.exec(select(LibraryReview).where(LibraryReview.id.in_(review_ids))).all()
    return sorted(rows, key=lambda row: (row.updated_at, row.id), reverse=True)


def get_paper_card(session: Session, paper_id: int, review_id=None) -> str:
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        return json.dumps({'error': f'paper {paper_id} not found'})

    wanted = str(review_id).strip() if review_id is not None else ''
    target = None
    if wanted:
        target = session.get(LibraryReview, wanted)
        if target is None:
            return json.dumps({'error': '综述任务不存在'}, ensure_ascii=False)

    reviews = _member_reviews(session, paper_id)
    selected = target or (reviews[0] if reviews else None)
    others = [row for row in reviews if selected is None or row.id != selected.id]

    row = session.exec(select(PaperCard).where(PaperCard.paper_id == paper_id)).first()
    result: dict[str, Any] = {
        'paper_id': paper.id,
        'title': paper.title,
        'card_status': row.status if row is not None else None,
        'review': _review_brief(selected) if selected is not None else None,
    }
    notes = []
    if target is not None and not any(member.id == target.id for member in reviews):
        notes.append('这篇论文不在该综述的论文列表中。')
    if others:
        result['other_reviews'] = [_review_brief(member) for member in others]
        notes.append('这篇论文属于多个综述，可传 review_id 指定一个。')
    if row is None:
        notes.append('这篇论文还没有精读卡，可用 get_paper_full_text 读取原文；'
                     '综述或文献地图运行后会生成卡片。')
    else:
        result.update(card_version=row.version, updated_at=utc_iso(row.updated_at),
                      model=row.model, warning=row.warning)
        card = json.loads(row.card_json or '{}')
        result['card'] = card
        result['verification'] = _verification_summary(card)
    if notes:
        result['note'] = ' '.join(notes)
    return json.dumps(result, ensure_ascii=False)


def _card_key_fields(card: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in CARD_FIELDS:
        field = card.get(name)
        if isinstance(field, dict):
            out[name] = {'value': field.get('value') or '', 'pages': field.get('pages') or [],
                         'status': field.get('status') or ''}
    contributions = [{'value': item.get('value') or '', 'pages': item.get('pages') or [],
                      'status': item.get('status') or ''}
                     for item in card.get('contributions') or [] if isinstance(item, dict)]
    if contributions:
        out['contributions'] = contributions
    return out


def _synthesis_view(entry) -> dict[str, Any]:
    """The stored synthesis without its internal fingerprint."""
    if not isinstance(entry, dict):
        return {}
    return {key: entry[key] for key in
            ('error', 'trend', 'open_questions', 'combination_opportunities', 'representative', 'stats')
            if entry.get(key) not in (None, '', [], {})}


def _theme_members(detail: dict, theme_id) -> list[dict]:
    return [p for p in detail.get('papers') or [] if theme_id in (p.get('themes') or [])]


def _find_theme(theme_list: list, query: str) -> tuple[dict | None, list]:
    """Match a theme by id or name; ambiguous names return their candidates."""
    wanted = str(query or '').strip().casefold()
    if not wanted:
        return None, []
    for theme in theme_list:
        if str(theme.get('id') or '').casefold() == wanted:
            return theme, []
    exact = [t for t in theme_list if str(t.get('name') or '').strip().casefold() == wanted]
    if len(exact) == 1:
        return exact[0], []
    partial = [t for t in theme_list if wanted in str(t.get('name') or '').casefold()]
    if len(partial) == 1:
        return partial[0], []
    return None, (exact or partial)


def _theme_brief(theme: dict) -> dict[str, Any]:
    return {'id': theme.get('id'), 'name': theme.get('name')}


def _read_theme(session: Session, base: dict, detail: dict, query: str, offset: int,
                status_note: str = '') -> str:
    theme_list = detail.get('themes') or []
    theme, candidates = _find_theme(theme_list, query)
    if theme is None:
        payload = {**base, 'status': detail.get('status'), 'theme_found': False,
                   'themes': [_theme_brief(t) for t in theme_list]}
        if candidates:
            payload['matching_themes'] = [_theme_brief(t) for t in candidates]
            payload['note'] = '主题名对应多个主题，请用返回的 id 指定。'
        else:
            payload['note'] = '没有匹配的主题，请用返回的 id 或名称再试。'
        return json.dumps(payload, ensure_ascii=False)

    tid = theme.get('id')
    members = _theme_members(detail, tid)
    total = len(members)
    offset = max(0, offset)
    page = members[offset:offset + PAPERS_PER_PAGE]
    page_ids = [entry['paper_id'] for entry in page]
    rows = {}
    if page_ids:
        rows = {row.paper_id: row for row in session.exec(
            select(PaperCard).where(PaperCard.paper_id.in_(page_ids)))}
    papers = []
    for entry in page:
        card_row = rows.get(entry['paper_id'])
        papers.append({'paper_id': entry['paper_id'], 'title': entry.get('title'),
                       'card_status': entry.get('card_status') or 'pending',
                       'card': _card_key_fields(json.loads(card_row.card_json or '{}'))
                       if card_row is not None else None})
    payload = {
        **base, 'status': detail.get('status'), 'stage': detail.get('stage') or '',
        'theme': {key: theme.get(key) for key in ('id', 'name', 'definition', 'include', 'exclude')},
        'synthesis': _synthesis_view((detail.get('syntheses') or {}).get(tid)),
        'papers': papers, 'paper_offset': offset, 'papers_total': total,
        'next_offset': offset + len(page) if offset + len(page) < total else None,
    }
    if status_note:
        payload['note'] = status_note
    return json.dumps(payload, ensure_ascii=False)


def read_literature_map(session: Session, review_id, theme=None, offset=0) -> str:
    from app.reviews.map import detail_map

    review_id = str(review_id)
    try:
        detail = detail_map(session, review_id)
    except LookupError:
        return json.dumps({'error': '综述任务不存在'}, ensure_ascii=False)

    job = session.get(LibraryReview, review_id)
    base = {'review_id': review_id, 'question': job.question if job is not None else ''}
    status = detail.get('status') or 'draft'
    themes = detail.get('themes') or []
    stage = detail.get('stage') or ''
    if not themes:
        payload = {**base, 'status': status, 'stage': stage}
        if status == 'running':
            payload['note'] = f'文献地图正在生成（{stage or "进行中"}），完成后再读取。'
        elif status == 'paused':
            payload['note'] = '文献地图已暂停且还没有主题，继续运行后再读取。'
        elif status == 'failed':
            payload['error'] = detail.get('error') or ''
            payload['note'] = '文献地图生成失败，重新运行后再读取。'
        else:
            payload['note'] = '这次综述还没有生成文献地图，可在综述页面运行文献地图。'
        return json.dumps(payload, ensure_ascii=False)

    status_note = ''
    if status == 'running':
        status_note = f'文献地图正在重新生成（{stage or "进行中"}），以下是上次已完成的结果。'
    elif status == 'paused':
        status_note = f'文献地图已暂停（{stage or "已暂停"}），以下是已完成部分。'
    elif status == 'failed':
        status_note = f'上次运行失败（{detail.get("error") or "未知原因"}），以下是已完成部分。'

    if theme is not None and str(theme).strip():
        return _read_theme(session, base, detail, str(theme).strip(), int(offset), status_note)

    offset = max(0, int(offset))
    page = themes[offset:offset + THEMES_PER_PAGE]
    entries = []
    truncated = False
    for item in page:
        tid = item.get('id')
        members = _theme_members(detail, tid)
        if len(members) > OVERVIEW_THEME_PAPERS:
            truncated = True
        entries.append({
            'id': tid, 'name': item.get('name'), 'definition': item.get('definition') or '',
            'include': item.get('include') or '', 'exclude': item.get('exclude') or '',
            'synthesis': _synthesis_view((detail.get('syntheses') or {}).get(tid)),
            'papers': [{'paper_id': p['paper_id'], 'title': p.get('title')}
                       for p in members[:OVERVIEW_THEME_PAPERS]],
            'papers_total': len(members),
        })
    counts = dict(detail.get('counts') or {})
    counts['themes'] = len(themes)
    payload = {
        **base, 'status': status, 'stage': stage,
        'version': detail.get('version'), 'overview': detail.get('overview') or {},
        'themes': entries, 'counts': counts,
        'theme_offset': offset, 'themes_total': len(themes),
        'next_offset': offset + len(page) if offset + len(page) < len(themes) else None,
    }
    notes = []
    if status_note:
        notes.append(status_note)
    if truncated:
        notes.append(f'部分主题论文较多，这里只列出前 {OVERVIEW_THEME_PAPERS} 篇；'
                     '用 theme 读取该主题的完整论文列表与卡片。')
    if notes:
        payload['note'] = ' '.join(notes)
    return json.dumps(payload, ensure_ascii=False)
