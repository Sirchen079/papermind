from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import TokenUsage

router = APIRouter()


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), session: Session = Depends(get_session)) -> dict:
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days - 1)
    rows = session.exec(select(TokenUsage).where(TokenUsage.day >= since)).all()

    total = 0
    by_kind: dict[str, int] = defaultdict(int)
    by_model: dict[str, int] = defaultdict(int)
    by_day: dict[str, int] = defaultdict(int)

    for r in rows:
        total += r.total_tokens
        by_kind[r.request_kind] += r.total_tokens
        by_model[r.model] += r.total_tokens
        by_day[r.day.isoformat()] += r.total_tokens

    return {
        "total_tokens": total,
        "by_kind": dict(by_kind),
        "by_model": dict(by_model),
        "by_day": [{"day": d, "tokens": t} for d, t in sorted(by_day.items())],
    }
