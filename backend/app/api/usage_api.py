from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import TokenUsage
from app.providers.cache_metrics import cache_diagnostics

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
        "input_tokens": sum(r.prompt_tokens for r in rows),
        "cached_input_tokens": sum(r.cached_input_tokens for r in rows),
        "cache_write_tokens": sum(r.cache_write_tokens for r in rows),
        "cache_reported_calls": sum(r.cache_usage_reported for r in rows),
        "cache_reported_input_tokens": sum(r.prompt_tokens for r in rows if r.cache_usage_reported),
        "call_count": len(rows),
        "cache_diagnostics": cache_diagnostics(rows),
        "by_kind": dict(by_kind),
        "by_model": dict(by_model),
        "by_day": [{"day": d, "tokens": t} for d, t in sorted(by_day.items())],
    }
