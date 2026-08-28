from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.thesis.service import (
    create_chapter,
    create_project,
    delete_chapter,
    delete_link,
    delete_project,
    export_thesis_markdown,
    get_thesis_workspace,
    link_paper,
    list_chapters,
    list_projects,
    patch_chapter,
    patch_link,
    patch_project,
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


@router.get("/thesis/workspace")
def thesis_workspace(session: Session = Depends(get_session)) -> dict:
    return _run(get_thesis_workspace, session)


@router.get("/thesis/export/markdown")
def thesis_markdown_export(
    project_id: int | None = None,
    chapter_id: int | None = None,
    session: Session = Depends(get_session),
) -> Response:
    content = _run(export_thesis_markdown, session, project_id=project_id, chapter_id=chapter_id)
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="papermind-thesis-materials.md"'},
    )


@router.get("/thesis/projects")
def thesis_projects(session: Session = Depends(get_session)) -> list[dict]:
    return _run(list_projects, session)


@router.post("/thesis/projects", status_code=201)
def add_thesis_project(body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(create_project, session, body.payload())


@router.patch("/thesis/projects/{project_id}")
def update_thesis_project(project_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(patch_project, session, project_id, body.payload())


@router.delete("/thesis/projects/{project_id}", status_code=204)
def remove_thesis_project(project_id: int, session: Session = Depends(get_session)) -> None:
    _run(delete_project, session, project_id)


@router.get("/thesis/projects/{project_id}/chapters")
def thesis_chapters(project_id: int, session: Session = Depends(get_session)) -> list[dict]:
    return _run(list_chapters, session, project_id)


@router.post("/thesis/projects/{project_id}/chapters", status_code=201)
def add_thesis_chapter(project_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(create_chapter, session, project_id, body.payload())


@router.patch("/thesis/chapters/{chapter_id}")
def update_thesis_chapter(chapter_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(patch_chapter, session, chapter_id, body.payload())


@router.delete("/thesis/chapters/{chapter_id}", status_code=204)
def remove_thesis_chapter(chapter_id: int, session: Session = Depends(get_session)) -> None:
    _run(delete_chapter, session, chapter_id)


@router.post("/papers/{paper_id}/thesis-links", status_code=201)
def add_paper_thesis_link(paper_id: int, body: PatchBody, session: Session = Depends(get_session)) -> dict:
    return _run(link_paper, session, paper_id, body.payload())


@router.patch("/papers/{paper_id}/thesis-links/{link_id}")
def update_paper_thesis_link(
    paper_id: int,
    link_id: int,
    body: PatchBody,
    session: Session = Depends(get_session),
) -> dict:
    return _run(patch_link, session, paper_id, link_id, body.payload())


@router.delete("/papers/{paper_id}/thesis-links/{link_id}", status_code=204)
def remove_paper_thesis_link(paper_id: int, link_id: int, session: Session = Depends(get_session)) -> None:
    _run(delete_link, session, paper_id, link_id)
