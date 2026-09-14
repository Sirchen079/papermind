import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.knowledge.suggest import generate_all
from app.models import Paper, Suggestion

router = APIRouter()


class StatusIn(BaseModel):
    status: str  # new | seen | dismissed | accepted


def _paper_is_visible(session: Session, paper_id: int | None) -> bool:
    if paper_id is None:
        return True
    paper = session.get(Paper, paper_id)
    return paper is not None and not paper.is_deleted


def _suggestion_is_visible(s: Suggestion, session: Session) -> bool:
    return _paper_is_visible(session, s.paper_id) and _paper_is_visible(session, s.related_paper_id)


def _parse_detail(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _public(s: Suggestion, session: Session) -> dict:
    detail = _parse_detail(s.detail_json)
    out = {
        "id": s.id,
        "kind": s.kind,
        "title": s.title,
        "detail": detail,
        "status": s.status,
        "weight": s.weight,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
    # resolve titles for linked papers so the UI can render without extra calls
    for field, key in (("paper_id", "paper"), ("related_paper_id", "related_paper")):
        pid = getattr(s, field)
        if pid:
            p = session.get(Paper, pid)
            out[key] = {"id": pid, "title": p.title if p else None}
    return out


@router.get("/suggestions")
def list_suggestions(
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict]:
    stmt = select(Suggestion)
    if status:
        stmt = stmt.where(Suggestion.status == status)
    stmt = stmt.order_by(Suggestion.weight.desc(), Suggestion.created_at.desc())
    return [_public(s, session) for s in session.exec(stmt).all() if _suggestion_is_visible(s, session)]


@router.patch("/suggestions/{sid}")
def patch_suggestion(sid: int, body: StatusIn, session: Session = Depends(get_session)) -> dict:
    s = session.get(Suggestion, sid)
    if s is None:
        raise HTTPException(404, "suggestion not found")
    allowed = {"new", "seen", "dismissed", "accepted"}
    if body.status not in allowed:
        raise HTTPException(400, f"status must be one of {sorted(allowed)}")
    s.status = body.status
    session.add(s)
    session.commit()
    return _public(s, session)


@router.post("/suggestions/generate")
def generate_suggestions(session: Session = Depends(get_session)) -> dict:
    """Scan the whole library for connections and central themes (idempotent)."""
    created = generate_all(session)
    return {"created": created}
