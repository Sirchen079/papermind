from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.models import Report
from app.reports.aggregation import weekly_aggregate
from app.reports.service import (
    ReportGenerationError,
    generate_weekly_report,
    get_report,
    list_reports,
)
from app.reports.pptx import report_pptx_bytes

router = APIRouter()


class GenerateIn(BaseModel):
    model_config = {"extra": "forbid"}

    since: str | None = None
    until: str | None = None
    problems: str | None = None


@router.get("/reports/weekly")
def api_weekly_aggregate(
    since: str | None = None,
    until: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """Deterministic weekly aggregates (P14.1) — zero LLM."""
    try:
        return weekly_aggregate(session, since=since, until=until)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/reports/weekly/generate", status_code=201)
def api_generate_weekly_report(body: GenerateIn, session: Session = Depends(get_session)) -> dict:
    """Aggregate + template + chat LLM → stored Report (P14.2).

    400 = 窗口/模板/LLM 配置问题；502 = LLM 调用失败。
    """
    try:
        return generate_weekly_report(session, since=body.since, until=body.until, problems=body.problems)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ReportGenerationError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/reports")
def api_list_reports(session: Session = Depends(get_session)) -> list[dict]:
    return list_reports(session)


@router.get("/reports/{report_id}")
def api_get_report(report_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return get_report(session, report_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/reports/{report_id}/markdown")
def api_report_markdown(report_id: int, session: Session = Depends(get_session)) -> Response:
    """Markdown download (P14.3)."""
    try:
        data = get_report(session, report_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    filename = f"papermind-report-{report_id}.md"
    return Response(
        content=data["content"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/{report_id}/pptx")
def api_report_pptx(report_id: int, session: Session = Depends(get_session)) -> Response:
    """Outline-style PPTX download (P14.3, python-pptx)."""
    row = session.get(Report, report_id)
    if row is None:
        raise HTTPException(404, "report not found")
    try:
        payload = report_pptx_bytes(row)
    except Exception as exc:  # noqa: BLE001 — corrupt content / pptx failure → 500-safe
        raise HTTPException(500, f"PPTX 生成失败：{exc}") from exc
    filename = f"papermind-report-{report_id}.pptx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
