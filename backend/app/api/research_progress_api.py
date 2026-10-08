from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from app.api.deps import get_session
from app.research_progress.service import export_research_progress_markdown, research_progress

router = APIRouter()


@router.get("/research/recent-work")
def recent_work(limit: int = Query(5, ge=1, le=20), session: Session = Depends(get_session)) -> dict:
    from app.workspaces.activity import recent_work as list_recent_work
    return list_recent_work(session, limit)


@router.get("/research/progress")
def progress(session: Session = Depends(get_session)) -> dict:
    return research_progress(session)


@router.get("/research/progress/markdown")
def progress_markdown(session: Session = Depends(get_session)) -> Response:
    return Response(
        content=export_research_progress_markdown(session),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="papermind-research-progress.md"'},
    )
