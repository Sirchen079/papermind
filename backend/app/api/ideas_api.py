from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.idea.service import (
    IdeaTransitionError,
    create_idea,
    delete_idea,
    get_idea,
    list_ideas,
    patch_idea,
    remove_paper_link,
    upsert_paper_link,
)

router = APIRouter()


class PaperLinkIn(BaseModel):
    model_config = {"extra": "forbid"}

    paper_id: int
    role: str
    note: str | None = None


class IdeaIn(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    content: str = ""
    hypothesis: str | None = None
    status: str | None = None
    priority: str | None = None
    origin: str | None = None
    project_id: int | None = None
    papers: list[PaperLinkIn] | None = None


class IdeaPatchIn(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = None
    content: str | None = None
    hypothesis: str | None = None
    status: str | None = None
    priority: str | None = None
    project_id: int | None = None


@router.get("/ideas")
def api_list_ideas(
    status: str | None = None,
    priority: str | None = None,
    project_id: int | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    try:
        return list_ideas(session, status=status, priority=priority, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/ideas", status_code=201)
def api_create_idea(body: IdeaIn, session: Session = Depends(get_session)) -> dict:
    try:
        idea = create_idea(
            session,
            title=body.title,
            content=body.content,
            hypothesis=body.hypothesis,
            status=body.status,
            priority=body.priority,
            origin=body.origin,
            project_id=body.project_id,
            paper_links=[link.model_dump() for link in (body.papers or [])],
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return get_idea(session, idea.id)


@router.get("/ideas/{idea_id}")
def api_get_idea(idea_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return get_idea(session, idea_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.patch("/ideas/{idea_id}")
def api_patch_idea(idea_id: int, body: IdeaPatchIn, session: Session = Depends(get_session)) -> dict:
    fields = body.model_dump(exclude_unset=True)
    try:
        patch_idea(session, idea_id, fields)
    except IdeaTransitionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return get_idea(session, idea_id)


@router.delete("/ideas/{idea_id}", status_code=204)
def api_delete_idea(idea_id: int, session: Session = Depends(get_session)) -> None:
    try:
        delete_idea(session, idea_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/ideas/{idea_id}/papers", status_code=201)
def api_link_paper(idea_id: int, body: PaperLinkIn, session: Session = Depends(get_session)) -> dict:
    try:
        link = upsert_paper_link(session, idea_id, body.paper_id, body.role, body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "idea_id": link.idea_id,
        "paper_id": link.paper_id,
        "role": link.role,
        "note": link.note,
    }


@router.delete("/ideas/{idea_id}/papers/{paper_id}/{role}", status_code=204)
def api_unlink_paper(
    idea_id: int, paper_id: int, role: str, session: Session = Depends(get_session)
) -> None:
    try:
        remove_paper_link(session, idea_id, paper_id, role)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/research-gaps")
def api_research_gaps(session: Session = Depends(get_session)) -> list[dict]:
    """Deterministic gap aggregation (matrix clusters, stale hubs, off-topic gems)."""
    from app.knowledge.gaps import research_gaps

    return research_gaps(session)
