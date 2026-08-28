from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from app.api.deps import get_session
from app.research_progress.service import export_research_progress_markdown, research_progress

router = APIRouter()


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
