from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.reading.service import (
    create_excerpt,
    create_note,
    delete_excerpt,
    delete_note,
    get_reading_workspace,
    list_review_matrix,
    patch_excerpt,
    patch_note,
    patch_reading_state,
    suggest_review_matrix,
    upsert_review_matrix,
)

router = APIRouter()


class PatchBody(BaseModel):
    model_config = {"extra": "allow"}

    def payload(self) -> dict[str, Any]:
        return dict(self.__pydantic_extra__ or {})


def _run(fn, *args, **kwargs):  # noqa: ANN001
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/papers/{paper_id}/reading")
def reading_workspace(paper_id: int, session: Session = Depends(get_session)) -> dict:
    return _run(get_reading_workspace, session, paper_id)


@router.patch("/papers/{paper_id}/reading/state")
def update_reading_state(paper_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(patch_reading_state, session, paper_id, body.payload())


@router.put("/papers/{paper_id}/reading/matrix")
def save_review_matrix(paper_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(upsert_review_matrix, session, paper_id, body.payload())


@router.post("/papers/{paper_id}/reading/matrix/suggest")
def suggest_matrix(paper_id: int, session: Session = Depends(get_session)) -> dict:
    return _run(suggest_review_matrix, session, paper_id)


@router.post("/papers/{paper_id}/reading/notes", status_code=201)
def add_note(paper_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(create_note, session, paper_id, body.payload())


@router.patch("/papers/{paper_id}/reading/notes/{note_id}")
def update_note(paper_id: int, note_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(patch_note, session, paper_id, note_id, body.payload())


@router.delete("/papers/{paper_id}/reading/notes/{note_id}", status_code=204)
def remove_note(paper_id: int, note_id: int, session: Session = Depends(get_session)) -> None:
    _run(delete_note, session, paper_id, note_id)


@router.post("/papers/{paper_id}/reading/excerpts", status_code=201)
def add_excerpt(paper_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(create_excerpt, session, paper_id, body.payload())


@router.patch("/papers/{paper_id}/reading/excerpts/{excerpt_id}")
def update_excerpt(paper_id: int, excerpt_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(patch_excerpt, session, paper_id, excerpt_id, body.payload())


@router.delete("/papers/{paper_id}/reading/excerpts/{excerpt_id}", status_code=204)
def remove_excerpt(paper_id: int, excerpt_id: int, session: Session = Depends(get_session)) -> None:
    _run(delete_excerpt, session, paper_id, excerpt_id)


@router.get("/reading/matrix")
def review_matrix(
    status: str | None = None,
    q: str | None = None,
    min_relevance: int | None = Query(default=None, ge=1, le=5),
    high_priority: bool = False,
    session: Session = Depends(get_session),
) -> list[dict]:
    return _run(
        list_review_matrix,
        session,
        status=status,
        q=q,
        min_relevance=min_relevance,
        high_priority=high_priority,
    )
