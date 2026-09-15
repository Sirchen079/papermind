from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.thesis.draft import DraftGenerationError, generate_draft, list_drafts
from app.thesis.service import (
    create_chapter,
    create_project,
    delete_chapter,
    delete_link,
    delete_project,
    export_bibtex,
    export_draft_markdown,
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


@router.get("/thesis/chapters/{chapter_id}/bibtex")
def thesis_chapter_bibtex(chapter_id: int, session: Session = Depends(get_session)) -> Response:
    """章节（含子章节）挂载论文的 .bib 导出（P10.6），key 用 citation_key。"""
    try:
        content, filename = export_bibtex(session, chapter_id=chapter_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=content,
        media_type="application/x-bibtex; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/thesis/projects/{project_id}/bibtex")
def thesis_project_bibtex(project_id: int, session: Session = Depends(get_session)) -> Response:
    """项目（含子项目、子树内章节）挂载论文的 .bib 导出（P10.6）。"""
    try:
        content, filename = export_bibtex(session, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=content,
        media_type="application/x-bibtex; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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


@router.post("/thesis/chapters/{chapter_id}/draft", status_code=201)
def generate_chapter_draft(chapter_id: int, session: Session = Depends(get_session)) -> dict:
    """LLM 生成章节草稿（P10.5）——无挂载论文/无 LLM → 400，LLM 失败 → 502。"""
    try:
        return generate_draft(session, chapter_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except DraftGenerationError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/thesis/chapters/{chapter_id}/drafts")
def list_chapter_drafts(chapter_id: int, session: Session = Depends(get_session)) -> list[dict]:
    """章节草稿版本历史（新→旧）。"""
    return list_drafts(session, chapter_id)


@router.get("/thesis/chapters/{chapter_id}/drafts/{draft_id}/markdown")
def chapter_draft_markdown(chapter_id: int, draft_id: int, session: Session = Depends(get_session)) -> Response:
    """T8：单个章节草稿的独立 Markdown 下载（文件名对 Unicode 安全）。"""
    try:
        content, filename = export_draft_markdown(session, chapter_id, draft_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    # RFC 6266/5987：ASCII 回退名 + filename* 承载中文文件名。
    disposition = (
        'attachment; filename="papermind-chapter-draft.md"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


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
