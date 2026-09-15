"""Weekly report aggregation (P14.1) — deterministic, zero LLM.

Everything counts rows whose timestamps fall inside ``[since 00:00,
until+1d 00:00)`` (naive UTC, matching ``app.models.base.utcnow``).
"""

import json
from collections import Counter
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.models import (
    Experiment,
    ExperimentLog,
    Idea,
    Paper,
    PaperExcerpt,
    PaperNote,
    PaperReadingState,
    Suggestion,
)
from app.models.base import utcnow

# AI-generated relation suggestions (P9.2 / P12.3), counted per kind.
AI_SUGGESTION_KINDS = ("method_conflict", "combination", "claim_relation")

DATE_FORMAT = "%Y-%m-%d"


def parse_window(since: str | None, until: str | None) -> tuple[datetime, datetime, date, date]:
    """Resolve ``since``/``until`` ISO dates into a UTC datetime window.

    Defaults: ``until`` = today (UTC), ``since`` = until - 6 days (a 7-day
    inclusive window). Raises ValueError on bad format or inverted range.
    Returns ``(start_dt, end_dt, since_date, until_date)``.
    """
    if until is None or not str(until).strip():
        until_date = utcnow().date()
    else:
        try:
            until_date = datetime.strptime(str(until).strip(), DATE_FORMAT).date()
        except ValueError as exc:
            raise ValueError(f"until 必须是 {DATE_FORMAT} 格式的日期") from exc

    if since is None or not str(since).strip():
        since_date = until_date - timedelta(days=6)
    else:
        try:
            since_date = datetime.strptime(str(since).strip(), DATE_FORMAT).date()
        except ValueError as exc:
            raise ValueError(f"since 必须是 {DATE_FORMAT} 格式的日期") from exc

    if since_date > until_date:
        raise ValueError("since 不能晚于 until")

    start = datetime(since_date.year, since_date.month, since_date.day)
    end = start + timedelta(days=(until_date - since_date).days + 1)
    return start, end, since_date, until_date


def _in_window(value: datetime | None, start: datetime, end: datetime) -> bool:
    return value is not None and start <= value < end


def weekly_aggregate(session: Session, since: str | None = None, until: str | None = None) -> dict:
    """Deterministic weekly aggregates for the group-meeting report."""
    start, end, since_date, until_date = parse_window(since, until)

    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    active_ids = {p.id for p in papers if p.id is not None}

    papers_new = sorted(
        (p for p in papers if _in_window(p.created_at, start, end)),
        key=lambda p: p.created_at or start,
    )
    states = session.exec(select(PaperReadingState)).all()
    papers_read = sum(1 for row in states if _in_window(row.finished_at, start, end))

    notes_new = sum(
        1
        for row in session.exec(select(PaperNote)).all()
        if _in_window(row.created_at, start, end) and row.paper_id in active_ids
    )
    excerpts_new = sum(
        1
        for row in session.exec(select(PaperExcerpt)).all()
        if _in_window(row.created_at, start, end) and row.paper_id in active_ids
    )

    ideas = session.exec(select(Idea).where(Idea.is_deleted == False)).all()  # noqa: E712
    ideas_created = [i for i in ideas if _in_window(i.created_at, start, end)]
    ideas_updated = [i for i in ideas if _in_window(i.updated_at, start, end)]
    updated_by_status = Counter(i.status for i in ideas_updated)
    ideas_closed = sum(1 for i in ideas if _in_window(i.closed_at, start, end))

    experiments = session.exec(select(Experiment).where(Experiment.is_deleted == False)).all()  # noqa: E712
    live_experiment_ids = {e.id for e in experiments if e.id is not None}
    experiments_created = [e for e in experiments if _in_window(e.created_at, start, end)]
    experiments_finished = [e for e in experiments if _in_window(e.finished_at, start, end)]
    status_counts = Counter(e.status for e in experiments)
    logs_added = sum(
        1
        for row in session.exec(select(ExperimentLog)).all()
        if _in_window(row.created_at, start, end) and row.experiment_id in live_experiment_ids
    )

    radar_high_items: list[dict] = []
    suggestions_ai_by_kind: Counter = Counter()
    for row in session.exec(select(Suggestion)).all():
        if not _in_window(row.created_at, start, end):
            continue
        if row.kind == "radar":
            try:
                detail = json.loads(row.detail_json or "{}")
            except json.JSONDecodeError:
                detail = {}
            if detail.get("grade") == "high":
                radar_high_items.append({"id": row.id, "title": row.title})
        elif row.kind in AI_SUGGESTION_KINDS:
            suggestions_ai_by_kind[row.kind] += 1

    return {
        "since": since_date.isoformat(),
        "until": until_date.isoformat(),
        "papers_new": {
            "count": len(papers_new),
            "items": [{"id": p.id, "title": p.title} for p in papers_new[:20]],
        },
        "papers_read": {"count": papers_read},
        "notes_new": {"count": notes_new},
        "excerpts_new": {"count": excerpts_new},
        "ideas": {
            "created": {
                "count": len(ideas_created),
                "items": [{"id": i.id, "title": i.title, "status": i.status} for i in ideas_created[:20]],
            },
            "updated": {
                "count": len(ideas_updated),
                "by_status": dict(updated_by_status),
            },
            "closed": {"count": ideas_closed},
        },
        "experiments": {
            "created": {
                "count": len(experiments_created),
                "items": [
                    {"id": e.id, "name": e.name, "status": e.status} for e in experiments_created[:20]
                ],
            },
            "logs_added": {"count": logs_added},
            "finished": {"count": len(experiments_finished)},
            "status_counts": dict(status_counts),
        },
        "radar_high": {
            "count": len(radar_high_items),
            "items": radar_high_items[:20],
        },
        "suggestions_ai": {
            "count": sum(suggestions_ai_by_kind.values()),
            "by_kind": dict(suggestions_ai_by_kind),
        },
    }


def render_aggregate_text(data: dict, problems: str | None = None) -> str:
    """Render the aggregate dict as a compact Chinese data block for the LLM prompt."""
    lines: list[str] = [f"统计区间：{data['since']} 至 {data['until']}（共 7 天内区间）"]

    papers = data["papers_new"]
    lines.append(f"新入库论文：{papers['count']} 篇")
    for item in papers["items"]:
        lines.append(f"  - {item['title'] or item['id']}")

    lines.append(f"本周读完：{data['papers_read']['count']} 篇")
    lines.append(f"新增笔记：{data['notes_new']['count']} 条；新增摘录：{data['excerpts_new']['count']} 条")

    ideas = data["ideas"]
    lines.append(
        f"Idea：新建 {ideas['created']['count']} 个，状态有更新 {ideas['updated']['count']} 个"
        f"（{ideas['updated']['by_status'] or '无'}），完结 {ideas['closed']['count']} 个"
    )
    for item in ideas["created"]["items"]:
        lines.append(f"  - 新建：{item['title']}（当前 {item['status']}）")

    experiments = data["experiments"]
    lines.append(
        f"实验：新建 {experiments['created']['count']} 个，追加日志 {experiments['logs_added']['count']} 条，"
        f"完结 {experiments['finished']['count']} 个，当前状态分布 {experiments['status_counts'] or '无'}"
    )
    for item in experiments["created"]["items"]:
        lines.append(f"  - 新建：{item['name']}（当前 {item['status']}）")

    radar = data["radar_high"]
    lines.append(f"文献雷达高相关新论文：{radar['count']} 篇")
    for item in radar["items"]:
        lines.append(f"  - {item['title']}")

    suggestions = data["suggestions_ai"]
    lines.append(f"AI 关联建议：{suggestions['count']} 条（按类型 {suggestions['by_kind'] or '无'}）")

    text = "\n".join(lines)
    if problems and problems.strip():
        text += f"\n\n用户填写的「本周遇到的问题」：\n{problems.strip()}"
    return text
