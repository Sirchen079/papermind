"""Literature radar: saved arXiv subscriptions, incremental pull, triage.

P10.1: subscription CRUD with validation.
P10.2: incremental pull (``refresh_all``) — startup background run + manual
"立即刷新". Entries already in the library or already surfaced before are
skipped via ``RadarSeen`` so re-pulls never re-suggest. P10.3 adds relevance
triage. See docs/superpowers/specs/2026-09-04-plan-b-p10-radar-writing-design.md.
"""
import json
import logging
import re
import threading
from datetime import timedelta

from sqlmodel import Session, select

from app.models import RadarSeen, Setting, Suggestion, Subscription
from app.models.base import utcnow

logger = logging.getLogger(__name__)

QUERY_TYPES = {"keyword", "category", "author"}
# Bounds keep a bad form value from turning one pull into an arXiv hammering.
MAX_RESULTS_MIN, MAX_RESULTS_MAX = 1, 100
LOOKBACK_MIN, LOOKBACK_MAX = 1, 365
# A subscription is due for the opportunistic startup run after this long.
RUN_INTERVAL = timedelta(hours=24)


def _validate(payload: dict) -> None:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("订阅名称不能为空")
    query_type = payload.get("query_type")
    if query_type not in QUERY_TYPES:
        raise ValueError(f"query_type 必须是 {'/'.join(sorted(QUERY_TYPES))}")
    if not str(payload.get("query_value") or "").strip():
        raise ValueError("查询内容不能为空")
    max_results = payload.get("max_results", 20)
    if not isinstance(max_results, int) or not (MAX_RESULTS_MIN <= max_results <= MAX_RESULTS_MAX):
        raise ValueError(f"max_results 必须在 {MAX_RESULTS_MIN}-{MAX_RESULTS_MAX} 之间")
    lookback_days = payload.get("lookback_days", 7)
    if not isinstance(lookback_days, int) or not (LOOKBACK_MIN <= lookback_days <= LOOKBACK_MAX):
        raise ValueError(f"lookback_days 必须在 {LOOKBACK_MIN}-{LOOKBACK_MAX} 之间")


def _dump(row: Subscription) -> dict:
    data = row.model_dump(mode="json")
    data["last_run_at"] = row.last_run_at.isoformat() if row.last_run_at else None
    data["created_at"] = row.created_at.isoformat() if row.created_at else None
    return data


def _row(session: Session, subscription_id: int) -> Subscription:
    row = session.get(Subscription, subscription_id)
    if row is None:
        raise LookupError("subscription not found")
    return row


def list_subscriptions(session: Session) -> list[dict]:
    rows = session.exec(select(Subscription).order_by(Subscription.id)).all()
    return [_dump(row) for row in rows]


def create_subscription(session: Session, payload: dict) -> dict:
    _validate(payload)
    row = Subscription(
        name=str(payload["name"]).strip(),
        query_type=payload["query_type"],
        query_value=str(payload["query_value"]).strip(),
        max_results=payload.get("max_results", 20),
        lookback_days=payload.get("lookback_days", 7),
        enabled=bool(payload.get("enabled", True)),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump(row)


def patch_subscription(session: Session, subscription_id: int, payload: dict) -> dict:
    row = _row(session, subscription_id)
    merged = {
        "name": payload.get("name", row.name),
        "query_type": payload.get("query_type", row.query_type),
        "query_value": payload.get("query_value", row.query_value),
        "max_results": payload.get("max_results", row.max_results),
        "lookback_days": payload.get("lookback_days", row.lookback_days),
        "enabled": payload.get("enabled", row.enabled),
    }
    _validate(merged)
    row.name = merged["name"]
    row.query_type = merged["query_type"]
    row.query_value = merged["query_value"]
    row.max_results = merged["max_results"]
    row.lookback_days = merged["lookback_days"]
    row.enabled = merged["enabled"]
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump(row)


def delete_subscription(session: Session, subscription_id: int) -> None:
    row = _row(session, subscription_id)
    session.delete(row)
    session.commit()


def is_due(subscription: Subscription, now=None) -> bool:
    """Due for the opportunistic run: enabled and last run ≥24h ago (or never)."""
    if not subscription.enabled:
        return False
    now = now or utcnow()
    return subscription.last_run_at is None or (now - subscription.last_run_at) >= RUN_INTERVAL


# --------------------------------------------------------------- P10.2 pull

def _clean_arxiv_id(entry_id: str) -> str:
    """`http://arxiv.org/abs/2401.00001v2` -> `2401.00001` (version stripped)."""
    raw = entry_id.rsplit("/abs/", 1)[-1]
    return re.sub(r"v\d+$", "", raw.strip())


def query_arxiv(subscription: Subscription) -> list[dict]:
    """Query arXiv for a subscription's recent entries (metadata only).

    Wrapped in one function so tests can monkeypatch it — the ``arxiv``
    package rides on ``requests`` (not httpx), so respx-style mocking does
    not apply. No PDF bytes here: full text downloads only on ingest.
    """
    import arxiv

    window_start = utcnow() - timedelta(days=subscription.lookback_days)
    date_from = window_start.strftime("%Y%m%d") + "0000"
    date_to = utcnow().strftime("%Y%m%d") + "2359"
    value = subscription.query_value.strip()
    if subscription.query_type == "category":
        core = f"cat:{value}"
    elif subscription.query_type == "author":
        core = f'au:"{value}"'
    else:
        core = f'all:"{value}"'
    search = arxiv.Search(
        query=f"{core} AND submittedDate:[{date_from} TO {date_to}]",
        max_results=subscription.max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )
    entries: list[dict] = []
    for result in arxiv.Client().results(search):
        published = getattr(result, "published", None)
        arxiv_id = _clean_arxiv_id(result.entry_id)
        entries.append(
            {
                "arxiv_id": arxiv_id,
                "title": (result.title or "").strip(),
                "abstract": (result.summary or "").strip(),
                "authors": [str(a) for a in result.authors],
                "published": published.isoformat() if published else None,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )
    return entries


def _mark_seen(session: Session, arxiv_id: str) -> None:
    if session.get(RadarSeen, arxiv_id) is None:
        session.add(RadarSeen(arxiv_id=arxiv_id))
        session.commit()


# ------------------------------------------------ P10.3 relevance triage

_GRADE_PROMPT = """你是一名科研文献助手。根据用户的「研究方向描述」，判断下面这篇 arXiv 新论文与该方向的相关度。

以 JSON 对象返回：{{"grade": "high 或 medium 或 low", "reason": "一句话中文理由"}}
high=与研究方向核心相关；medium=有一定关联、值得看一眼；low=基本无关。
仅返回 JSON 本身（不要解释文字，不要 markdown 代码块标记）。

研究方向描述：{interests}

论文标题：{title}
摘要：{abstract}"""

VALID_GRADES = {"high", "medium", "low"}
# Reason recorded when the chat LLM call itself fails: the entry still
# surfaces as medium, only the grade's provenance changes (P10.3).
_LLM_UNAVAILABLE = "llm_unavailable"


def research_interests(session: Session) -> str:
    """The user's free-text research direction (Setting key research_interests)."""
    row = session.get(Setting, "research_interests")
    return (row.value or "").strip() if row else ""


def _strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    return text.strip()


def _grade_entry(client, provider, model_id, interests: str, entry: dict) -> dict:
    """Ask the chat LLM to grade one entry high/medium/low.

    Every failure — network error, malformed JSON, unknown grade — degrades
    to medium so the entry is never silently dropped (P10.3).
    """
    prompt = _GRADE_PROMPT.format(
        interests=interests,
        title=entry.get("title") or "（无标题）",
        abstract=(entry.get("abstract") or "")[:3000],
    )
    try:
        result = client.complete(
            provider,
            model_id,
            [{"role": "user", "content": prompt}],
            request_kind="ingest",
        )
        parsed = json.loads(_strip_json_fence(result.content))
        grade = parsed.get("grade")
        if grade in VALID_GRADES:
            return {"grade": grade, "reason": str(parsed.get("reason") or "").strip()}
    except Exception:  # noqa: BLE001 — degradation is the contract
        pass
    return {"grade": "medium", "reason": _LLM_UNAVAILABLE}


def _entry_grader(session: Session):
    """Return a callable(entry)->{grade, reason}, or None to degrade all to medium.

    Grading needs both a research-direction description and a configured chat
    LLM; missing either means every entry is surfaced as medium.
    """
    from app.providers.selection import pick_llm

    interests = research_interests(session)
    if not interests:
        return None
    ctx = pick_llm(session, "chat")
    if ctx is None:
        return None
    client, provider, model_id = ctx
    return lambda entry: _grade_entry(client, provider, model_id, interests, entry)


_MEDIUM = {"grade": "medium", "reason": ""}


def refresh_subscription(
    session: Session, subscription: Subscription, query_fn=None
) -> dict:
    """Pull one subscription; surface new entries as radar suggestions.

    Entries are graded against the user's research interests (P10.3): low is
    remembered-but-not-surfaced, everything else becomes a suggestion. Skips
    entries already in the library (arxiv_id / title_norm dedup) and entries
    already surfaced once (RadarSeen) — both are marked seen so they never
    re-suggest. Any network/API error propagates to the caller of
    ``refresh_all`` (per-subscription failure isolation). ``query_fn``
    defaults to ``query_arxiv`` resolved late so tests can monkeypatch the
    module attribute even through the API layer.
    """
    from app.ingestion.service import find_duplicate

    query_fn = query_fn or query_arxiv
    grader = _entry_grader(session)
    entries = query_fn(subscription)
    new_entries = 0
    for entry in entries:
        arxiv_id = str(entry.get("arxiv_id") or "").strip()
        if not arxiv_id:
            continue
        if session.get(RadarSeen, arxiv_id) is not None:
            continue
        existing = find_duplicate(session, None, arxiv_id, entry.get("title"))
        _mark_seen(session, arxiv_id)
        if existing is not None:
            continue  # already in the library — remembered, not suggested
        grade_info = grader(entry) if grader else _MEDIUM
        if grade_info["grade"] == "low":
            continue  # remembered above; not relevant enough to surface
        session.add(
            Suggestion(
                kind="radar",
                title=entry.get("title") or arxiv_id,
                detail_json=json.dumps(
                    {
                        "arxiv_id": arxiv_id,
                        "abstract": entry.get("abstract") or "",
                        "authors": entry.get("authors") or [],
                        "published": entry.get("published"),
                        "url": entry.get("url") or f"https://arxiv.org/abs/{arxiv_id}",
                        "subscription": subscription.name,
                        "grade": grade_info["grade"],
                        "grade_reason": grade_info.get("reason") or "",
                    },
                    ensure_ascii=False,
                ),
                weight=1.0,
                dedup_key=f"radar:{arxiv_id}",
            )
        )
        session.commit()
        new_entries += 1
    subscription.last_run_at = utcnow()
    session.add(subscription)
    session.commit()
    return {
        "subscription_id": subscription.id,
        "name": subscription.name,
        "status": "ok",
        "new_entries": new_entries,
        "error": None,
    }


def due_subscriptions(session: Session) -> list[Subscription]:
    return [sub for sub in session.exec(select(Subscription)).all() if is_due(sub)]


def refresh_all(session: Session, force: bool = False, query_fn=None) -> dict:
    """Refresh every enabled subscription that is due (all of them on force).

    One subscription's failure never aborts the run: it is reported with
    ``status="error"`` and the rest keep going.
    """
    query_fn = query_fn or query_arxiv
    results: list[dict] = []
    for sub in session.exec(select(Subscription)).all():
        if sub.enabled is False:
            continue
        if not force and not is_due(sub):
            continue
        try:
            results.append(refresh_subscription(session, sub, query_fn=query_fn))
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            results.append(
                {
                    "subscription_id": sub.id,
                    "name": sub.name,
                    "status": "error",
                    "new_entries": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return {
        "ran": len(results),
        "created": sum(r["new_entries"] for r in results),
        "results": results,
        "ran_at": utcnow().isoformat(),
    }


def radar_status(session: Session) -> dict:
    """Cheap dashboard summary — no network, no pull."""
    subs = session.exec(select(Subscription)).all()
    enabled = [s for s in subs if s.enabled]
    last_run = max((s.last_run_at for s in subs if s.last_run_at), default=None)
    return {
        "total": len(subs),
        "enabled": len(enabled),
        "due": sum(1 for s in enabled if is_due(s)),
        "last_run_at": last_run.isoformat() if last_run else None,
    }


def start_background_refresh() -> None:
    """Kick the opportunistic startup pull on a daemon thread.

    Uses its own short-lived session (a fresh test DB has no subscriptions,
    so the thread is a no-op there). Every error is swallowed — the radar is
    opportunistic and must never break app startup. Set
    ``PAPERMIND_DISABLE_RADAR_AUTORUN`` to skip (tests / debugging).
    """
    import os

    if os.environ.get("PAPERMIND_DISABLE_RADAR_AUTORUN"):
        return

    def _run() -> None:
        try:
            from app.db.engine import get_engine

            with Session(get_engine()) as session:
                refresh_all(session, force=False)
        except Exception:  # noqa: BLE001 — never break startup
            logger.warning(
                "step=radar_background_refresh failed; startup continues",
                exc_info=True,
            )

    from contextvars import copy_context
    context = copy_context()
    threading.Thread(target=lambda: context.run(_run), name="radar-startup", daemon=True).start()
