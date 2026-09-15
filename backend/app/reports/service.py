"""Group-meeting report generation (P14.2).

Deterministic aggregation supplies the data; the shared chat LLM only
reorganizes it into Chinese markdown following the bundled
``group-meeting-report`` template skill (type=template, trigger=manual).
The result is stored as a ``Report`` row.
"""

from datetime import timedelta

from sqlmodel import Session, select

from app.models import Report, Skill
from app.reports.aggregation import parse_window, render_aggregate_text, weekly_aggregate

TEMPLATE_SKILL_NAME = "group-meeting-report"
AGGREGATES_TOKEN = "{{aggregates}}"


class ReportGenerationError(RuntimeError):
    """The LLM call failed or returned nothing usable (API maps to 502)."""


def _strip_outer_fence(text: str) -> str:
    """Drop one wrapping ```… fence if the model added one."""
    text = (text or "").strip()
    if text.startswith("```") and text.count("```") >= 2:
        inner = text.split("```", 2)[1]
        if inner.lstrip().lower().startswith("markdown"):
            inner = inner.lstrip()[8:]
        text = inner.strip()
    return text


def _load_template_body(session: Session) -> str:
    """Template body from the Skill table; lazily loads bundled skills once.

    Users can edit the template in the Skills page (the DB row wins over the
    bundled file; startup loads insert-only so edits are preserved).
    """
    skill = session.exec(select(Skill).where(Skill.name == TEMPLATE_SKILL_NAME)).first()
    if skill is None or not (skill.body or "").strip():
        from app.api.skills_api import default_skills_dir
        from app.skills.loader import load_skills_from_dir

        load_skills_from_dir(session, default_skills_dir(), overwrite=False)
        skill = session.exec(select(Skill).where(Skill.name == TEMPLATE_SKILL_NAME)).first()
    if skill is None or not (skill.body or "").strip():
        raise ValueError(
            f"缺少组会汇报模板技能「{TEMPLATE_SKILL_NAME}」，请在技能页恢复或新建该模板"
        )
    return skill.body or ""


def _dump(row: Report) -> dict:
    return {
        "id": row.id,
        "since": row.since.isoformat(),
        "until": row.until.isoformat(),
        "content": row.content,
        "model": row.model,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def generate_weekly_report(
    session: Session,
    since: str | None = None,
    until: str | None = None,
    problems: str | None = None,
) -> dict:
    """Aggregate → template → chat LLM → stored Report.

    Raises ValueError (bad window / no template / no LLM — API → 400) or
    ReportGenerationError (LLM failed — API → 502).
    """
    from app.providers.selection import pick_llm

    start, end, _since_date, _until_date = parse_window(since, until)
    data = weekly_aggregate(session, since=since, until=until)
    template = _load_template_body(session)

    if AGGREGATES_TOKEN not in template:
        raise ValueError(f"组会汇报模板缺少占位符 {AGGREGATES_TOKEN}")
    prompt = template.replace(AGGREGATES_TOKEN, render_aggregate_text(data, problems))

    ctx = pick_llm(session, "chat")
    if ctx is None:
        raise ValueError("未配置 LLM 提供商，无法生成组会汇报")
    client, provider, model_id = ctx

    try:
        result = client.complete(
            provider,
            model_id,
            [{"role": "user", "content": prompt}],
            request_kind="ingest",
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as 502 with reason
        raise ReportGenerationError(f"{type(exc).__name__}: {exc}") from exc
    content = _strip_outer_fence(result.content or "")
    if not content:
        raise ReportGenerationError("模型返回了空内容，请重试或更换模型")

    report = Report(
        since=start,
        # store the inclusive last day (midnight), not the exclusive window end
        until=end - timedelta(days=1),
        content=content,
        model=model_id,
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return _dump(report)


def list_reports(session: Session) -> list[dict]:
    """Generation history, newest first."""
    rows = session.exec(
        select(Report).order_by(Report.created_at.desc(), Report.id.desc())
    ).all()
    return [_dump(row) for row in rows]


def get_report(session: Session, report_id: int) -> dict:
    row = session.get(Report, report_id)
    if row is None:
        raise LookupError("report not found")
    return _dump(row)
