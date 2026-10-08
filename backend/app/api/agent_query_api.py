"""Read-only library queries for external AI CLI tools (Claude Code, Codex, ZCode…).

These endpoints intentionally require the local token, unlike the SPA's own
read APIs: the audience is any local process the user pointed at PaperMind,
so the per-installation credential in ``<data dir>/api_token`` gates access
(the SPA receives the same token via the index.html meta tag). Everything
here is read-only and reuses the exact building blocks the in-app chat agent
uses, so external tools and the assistant see the same library.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, func, select

from app.api.deps import get_session
from app.models import Paper, PaperChunk
from app.security.local_token import require_local_token

router = APIRouter(dependencies=[Depends(require_local_token)])


def _recent_papers(session: Session, limit: int = 10) -> list[dict]:
    rows = session.exec(
        select(Paper)
        .where(Paper.is_deleted == False)  # noqa: E712 - SQL expression
        .order_by(Paper.updated_at.desc(), Paper.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            'id': paper.id,
            'title': paper.title,
            'year': paper.year,
            'has_pdf': bool(paper.pdf_path),
            'updated_at': paper.updated_at.isoformat() if paper.updated_at else None,
        }
        for paper in rows
    ]


@router.get('/agent/summary')
def agent_summary(request: Request, session: Session = Depends(get_session)) -> dict:
    """Orient an external tool: app version, library size, recent activity."""
    papers = session.exec(
        select(func.count(Paper.id)).where(Paper.is_deleted == False)  # noqa: E712
    ).one()
    indexed = len(
        session.exec(
            select(PaperChunk.paper_id).where(PaperChunk.paper_id.is_not(None)).distinct()
        ).all()
    )
    from app.agent.saved_documents import list_documents

    documents = list_documents(session, query='', offset=0, limit=10)
    return {
        'app': 'PaperMind',
        'version': getattr(request.app, 'version', ''),
        'papers': {'total': papers, 'indexed': indexed, 'recent': _recent_papers(session)},
        'saved_documents': {
            'total': documents.get('total', len(documents.get('items', [])))
            if isinstance(documents, dict)
            else len(documents),
            'recent': [
                {
                    'message_id': item.get('message_id'),
                    'filename': item.get('filename'),
                    'created_at': item.get('created_at'),
                }
                for item in (documents.get('items', []) if isinstance(documents, dict) else documents)
            ],
        },
        'note': '只读接口。正文检索用 /api/agent/search；论文列表用 /api/papers；全文用 /api/papers/{id}/document/markdown。',
    }


@router.get('/agent/search')
def agent_search(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(6, ge=1, le=12),
    paper_ids: str | None = Query(None, description='comma-separated paper ids'),
    session: Session = Depends(get_session),
):
    """Run the same hybrid library retrieval the chat agent uses.

    Semantic recall may call the configured embedding provider; if that fails
    the response degrades to local keyword results, exactly like in-app search.
    """
    ids = None
    if paper_ids is not None:
        try:
            ids = [int(part) for part in paper_ids.split(',') if part.strip()]
        except ValueError as exc:
            raise HTTPException(422, 'paper_ids 应为逗号分隔的论文编号。') from exc
        ids = list(dict.fromkeys(ids)) or None
    from app.agent.paper_search import search_paper_text

    raw = search_paper_text(session, q.strip(), ids, top_k)
    try:
        return json.loads(raw)
    except ValueError:  # pragma: no cover - the tool always returns JSON
        return [{'note': raw}]
