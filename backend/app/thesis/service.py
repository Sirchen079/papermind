from collections import defaultdict

from sqlmodel import Session, select

from app.models import Chapter, Paper, PaperExcerpt, PaperLink, PaperNote, PaperReadingState, Project, ReviewMatrixEntry
from app.models.base import utcnow
from app.models.paper import parse_authors_json

PROJECT_KINDS = {"direction", "topic", "experiment", "writing", "other"}
PROJECT_STATUSES = {"active", "paused", "done", "archived"}
CHAPTER_STATUSES = {"draft", "in_progress", "review", "done"}
LINK_ROLES = {"background", "method", "comparison", "evidence", "limitation", "inspiration", "related", "to_read"}
ROLE_LABELS = {
    "background": "背景",
    "method": "方法",
    "comparison": "对比",
    "evidence": "证据",
    "limitation": "局限",
    "inspiration": "启发",
    "related": "相关",
    "to_read": "待读",
}
READING_STATUS_LABELS = {
    "unread": "未读",
    "queued": "待处理",
    "reading": "阅读中",
    "read": "已读",
    "skipped": "跳过",
}
READING_PRIORITY_LABELS = {"low": "低", "normal": "普通", "high": "高"}
NOTE_KIND_LABELS = {"note": "笔记", "question": "问题", "idea": "想法", "critique": "批注", "todo": "待办"}
MATRIX_FIELD_LABELS = [
    ("problem", "问题"),
    ("method", "方法"),
    ("dataset", "数据集"),
    ("metrics", "指标"),
    ("results", "结果"),
    ("limitations", "局限"),
    ("novelty", "创新点"),
    ("relation_to_thesis", "与论文关系"),
    ("future_work", "未来工作"),
    ("notes", "备注"),
]


def _paper(session: Session, paper_id: int) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        raise LookupError("paper not found")
    return paper


def _project_row(session: Session, project_id: int) -> Project:
    row = session.get(Project, project_id)
    if row is None:
        raise LookupError("project not found")
    return row


def _chapter_row(session: Session, chapter_id: int) -> Chapter:
    row = session.get(Chapter, chapter_id)
    if row is None:
        raise LookupError("chapter not found")
    return row


def _dump(row: object) -> dict:
    return row.model_dump(mode="json")  # type: ignore[attr-defined]


def _validate_project_payload(payload: dict) -> None:
    if not str(payload.get("name") or "").strip():
        raise ValueError("project name is required")
    if payload.get("kind", "topic") not in PROJECT_KINDS:
        raise ValueError("invalid project kind")
    if payload.get("status", "active") not in PROJECT_STATUSES:
        raise ValueError("invalid project status")


def _validate_chapter_payload(payload: dict) -> None:
    if not str(payload.get("title") or "").strip():
        raise ValueError("chapter title is required")
    if payload.get("status", "draft") not in CHAPTER_STATUSES:
        raise ValueError("invalid chapter status")


def _validate_link_payload(payload: dict) -> None:
    if payload.get("role", "related") not in LINK_ROLES:
        raise ValueError("invalid link role")
    has_project = payload.get("project_id") is not None
    has_chapter = payload.get("chapter_id") is not None
    if has_project == has_chapter:
        raise ValueError("paper link must target exactly one project or chapter")


def _project_children(session: Session, parent_id: int | None) -> list[Project]:
    stmt = select(Project).where(Project.parent_project_id == parent_id).order_by(Project.sort_order, Project.id)
    return session.exec(stmt).all()


def _chapter_children(session: Session, project_id: int, parent_id: int | None) -> list[Chapter]:
    stmt = (
        select(Chapter)
        .where(Chapter.project_id == project_id, Chapter.parent_chapter_id == parent_id)
        .order_by(Chapter.sort_order, Chapter.id)
    )
    return session.exec(stmt).all()


def _project_descendant_ids(session: Session, project_id: int) -> set[int]:
    descendants: set[int] = set()
    stack = [project_id]
    while stack:
        current = stack.pop()
        children = session.exec(select(Project).where(Project.parent_project_id == current)).all()
        for child in children:
            if child.id is None or child.id in descendants:
                continue
            descendants.add(child.id)
            stack.append(child.id)
    return descendants


def _chapter_descendant_ids(session: Session, project_id: int, chapter_id: int) -> set[int]:
    descendants: set[int] = set()
    stack = [chapter_id]
    while stack:
        current = stack.pop()
        children = session.exec(
            select(Chapter).where(Chapter.project_id == project_id, Chapter.parent_chapter_id == current)
        ).all()
        for child in children:
            if child.id is None or child.id in descendants:
                continue
            descendants.add(child.id)
            stack.append(child.id)
    return descendants


def list_projects(session: Session) -> list[dict]:
    rows = session.exec(select(Project).order_by(Project.sort_order, Project.id)).all()
    return [_dump(row) for row in rows]


def list_chapters(session: Session, project_id: int) -> list[dict]:
    _project_row(session, project_id)
    rows = session.exec(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sort_order, Chapter.id)
    ).all()
    return [_dump(row) for row in rows]


def create_project(session: Session, payload: dict) -> dict:
    _validate_project_payload(payload)
    parent_id = payload.get("parent_project_id")
    if parent_id is not None:
        _project_row(session, parent_id)
    row = Project(
        parent_project_id=parent_id,
        kind=payload.get("kind", "topic"),
        name=str(payload["name"]).strip(),
        description=payload.get("description"),
        status=payload.get("status", "active"),
        sort_order=int(payload.get("sort_order") or 0),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump(row)


def patch_project(session: Session, project_id: int, payload: dict) -> dict:
    row = _project_row(session, project_id)
    if "name" in payload:
        name = str(payload["name"] or "").strip()
        if not name:
            raise ValueError("project name is required")
        row.name = name
    if "kind" in payload:
        if payload["kind"] not in PROJECT_KINDS:
            raise ValueError("invalid project kind")
        row.kind = payload["kind"]
    if "description" in payload:
        row.description = payload["description"]
    if "status" in payload:
        if payload["status"] not in PROJECT_STATUSES:
            raise ValueError("invalid project status")
        row.status = payload["status"]
    if "parent_project_id" in payload:
        parent_id = payload["parent_project_id"]
        if parent_id == project_id:
            raise ValueError("project cannot be its own parent")
        if parent_id is not None:
            _project_row(session, parent_id)
            if parent_id in _project_descendant_ids(session, project_id):
                raise ValueError("project cannot use a descendant as parent")
        row.parent_project_id = parent_id
    if "sort_order" in payload:
        row.sort_order = int(payload["sort_order"] or 0)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump(row)


def delete_project(session: Session, project_id: int) -> None:
    row = _project_row(session, project_id)
    if session.exec(select(Project).where(Project.parent_project_id == project_id)).first() is not None:
        raise ValueError("project has child projects; move or delete them first")
    if session.exec(select(Chapter).where(Chapter.project_id == project_id)).first() is not None:
        raise ValueError("project has chapters; move or delete them first")
    if session.exec(select(PaperLink).where(PaperLink.project_id == project_id)).first() is not None:
        raise ValueError("project has linked papers; detach them first")
    session.delete(row)
    session.commit()


def create_chapter(session: Session, project_id: int, payload: dict) -> dict:
    _project_row(session, project_id)
    _validate_chapter_payload(payload)
    parent_id = payload.get("parent_chapter_id")
    if parent_id is not None:
        parent = _chapter_row(session, parent_id)
        if parent.project_id != project_id:
            raise ValueError("parent chapter must belong to the same project")
    row = Chapter(
        project_id=project_id,
        parent_chapter_id=parent_id,
        title=str(payload["title"]).strip(),
        outline=payload.get("outline"),
        sort_order=int(payload.get("sort_order") or 0),
        status=payload.get("status", "draft"),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump(row)


def patch_chapter(session: Session, chapter_id: int, payload: dict) -> dict:
    row = _chapter_row(session, chapter_id)
    if "title" in payload:
        title = str(payload["title"] or "").strip()
        if not title:
            raise ValueError("chapter title is required")
        row.title = title
    if "outline" in payload:
        row.outline = payload["outline"]
    if "status" in payload:
        if payload["status"] not in CHAPTER_STATUSES:
            raise ValueError("invalid chapter status")
        row.status = payload["status"]
    if "parent_chapter_id" in payload:
        parent_id = payload["parent_chapter_id"]
        if parent_id == chapter_id:
            raise ValueError("chapter cannot be its own parent")
        if parent_id is not None:
            parent = _chapter_row(session, parent_id)
            if parent.project_id != row.project_id:
                raise ValueError("parent chapter must belong to the same project")
            if parent_id in _chapter_descendant_ids(session, row.project_id, chapter_id):
                raise ValueError("chapter cannot use a descendant as parent")
        row.parent_chapter_id = parent_id
    if "sort_order" in payload:
        row.sort_order = int(payload["sort_order"] or 0)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump(row)


def delete_chapter(session: Session, chapter_id: int) -> None:
    row = _chapter_row(session, chapter_id)
    if session.exec(select(Chapter).where(Chapter.parent_chapter_id == chapter_id)).first() is not None:
        raise ValueError("chapter has child chapters; move or delete them first")
    if session.exec(select(PaperLink).where(PaperLink.chapter_id == chapter_id)).first() is not None:
        raise ValueError("chapter has linked papers; detach them first")
    session.delete(row)
    session.commit()


def link_paper(session: Session, paper_id: int, payload: dict) -> dict:
    _paper(session, paper_id)
    _validate_link_payload(payload)
    project_id = payload.get("project_id")
    chapter_id = payload.get("chapter_id")
    if project_id is not None:
        _project_row(session, project_id)
    if chapter_id is not None:
        chapter = _chapter_row(session, chapter_id)
        if project_id is not None and chapter.project_id != project_id:
            raise ValueError("chapter must belong to the selected project")
    row = PaperLink(
        paper_id=paper_id,
        project_id=project_id,
        chapter_id=chapter_id,
        role=payload.get("role", "related"),
        note=payload.get("note"),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump(row)


def patch_link(session: Session, paper_id: int, link_id: int, payload: dict) -> dict:
    row = session.get(PaperLink, link_id)
    if row is None or row.paper_id != paper_id:
        raise LookupError("link not found")
    if "project_id" in payload or "chapter_id" in payload or "role" in payload:
        new_payload = {
            "project_id": payload.get("project_id", row.project_id),
            "chapter_id": payload.get("chapter_id", row.chapter_id),
            "role": payload.get("role", row.role),
        }
        _validate_link_payload(new_payload)
    if "project_id" in payload:
        project_id = payload["project_id"]
        if project_id is not None:
            _project_row(session, project_id)
        row.project_id = project_id
    if "chapter_id" in payload:
        chapter_id = payload["chapter_id"]
        if chapter_id is not None:
            chapter = _chapter_row(session, chapter_id)
            if row.project_id is not None and chapter.project_id != row.project_id:
                raise ValueError("chapter must belong to the selected project")
        row.chapter_id = chapter_id
    if "role" in payload:
        if payload["role"] not in LINK_ROLES:
            raise ValueError("invalid link role")
        row.role = payload["role"]
    if "note" in payload:
        row.note = payload["note"]
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump(row)


def delete_link(session: Session, paper_id: int, link_id: int) -> None:
    row = session.get(PaperLink, link_id)
    if row is None or row.paper_id != paper_id:
        raise LookupError("link not found")
    session.delete(row)
    session.commit()


def _tree_children_project(session: Session, parent_id: int | None) -> list[dict]:
    out = []
    for project in _project_children(session, parent_id):
        out.append(
            {
                **_dump(project),
                "children": _tree_children_project(session, project.id),
                "chapters": _chapter_tree(session, project.id, None),
            }
        )
    return out


def _chapter_tree(session: Session, project_id: int, parent_id: int | None) -> list[dict]:
    out = []
    for chapter in _chapter_children(session, project_id, parent_id):
        out.append({**_dump(chapter), "children": _chapter_tree(session, project_id, chapter.id)})
    return out


def _link_papers(session: Session) -> dict[int, list[dict]]:
    links = session.exec(select(PaperLink)).all()
    by_paper: dict[int, list[dict]] = defaultdict(list)
    for link in links:
        by_paper[link.paper_id].append(_dump(link))
    return by_paper


def get_thesis_workspace(session: Session) -> dict:
    projects = _tree_children_project(session, None)
    links = _link_papers(session)
    paper_ids = list(links)
    if not paper_ids:
        return {"projects": projects, "papers": []}
    papers = session.exec(select(Paper).where(Paper.is_deleted == False, Paper.id.in_(paper_ids))).all()  # noqa: E712
    paper_rows = []
    for paper in papers:
        paper_rows.append(
            {
                "id": paper.id,
                "title": paper.title,
                "year": paper.year,
                "authors": parse_authors_json(paper.authors_json),
                "links": links.get(paper.id, []),
            }
        )
    return {"projects": projects, "papers": paper_rows}


def _project_path(session: Session, project_id: int) -> str:
    parts: list[str] = []
    current = _project_row(session, project_id)
    while current is not None:
        parts.append(current.name)
        if current.parent_project_id is None:
            break
        current = _project_row(session, current.parent_project_id)
    return " / ".join(reversed(parts))


def _chapter_path(session: Session, chapter_id: int) -> str:
    chapter = _chapter_row(session, chapter_id)
    parts = [chapter.title]
    parent_id = chapter.parent_chapter_id
    while parent_id is not None:
        parent = _chapter_row(session, parent_id)
        parts.append(parent.title)
        parent_id = parent.parent_chapter_id
    return f"{_project_path(session, chapter.project_id)} / {' / '.join(reversed(parts))}"


def _scope_links(session: Session, project_id: int | None, chapter_id: int | None) -> tuple[str, list[PaperLink]]:
    if (project_id is None) == (chapter_id is None):
        raise ValueError("choose exactly one project or chapter")

    if project_id is not None:
        _project_row(session, project_id)
        project_ids = {project_id, *_project_descendant_ids(session, project_id)}
        chapters = session.exec(select(Chapter).where(Chapter.project_id.in_(project_ids))).all()
        chapter_ids = {chapter.id for chapter in chapters if chapter.id is not None}
        scope = f"项目 · {_project_path(session, project_id)}"
        links = [
            link
            for link in session.exec(select(PaperLink)).all()
            if (link.project_id in project_ids) or (link.chapter_id in chapter_ids)
        ]
        return scope, links

    chapter = _chapter_row(session, chapter_id or 0)
    chapter_ids = {chapter.id, *_chapter_descendant_ids(session, chapter.project_id, chapter.id or 0)}
    scope = f"章节 · {_chapter_path(session, chapter.id or 0)}"
    links = [link for link in session.exec(select(PaperLink)).all() if link.chapter_id in chapter_ids]
    return scope, links


def _target_label(session: Session, link: PaperLink) -> str:
    if link.chapter_id is not None:
        return f"章节 · {_chapter_path(session, link.chapter_id)}"
    if link.project_id is not None:
        return f"项目 · {_project_path(session, link.project_id)}"
    return "未知目标"


def _inline(value: object) -> str:
    return str(value or "").strip().replace("\r\n", "\n").replace("\n", " / ")


def _tags(value: str | None) -> list[str]:
    if not value:
        return []
    import json

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _state_line(row: PaperReadingState | None) -> str:
    status = READING_STATUS_LABELS.get(row.status if row else "unread", row.status if row else "未读")
    priority = READING_PRIORITY_LABELS.get(row.priority if row else "normal", row.priority if row else "普通")
    parts = [f"阅读状态：{status}", f"优先级：{priority}"]
    if row and row.rating is not None:
        parts.append(f"评分：{row.rating}")
    if row and row.relevance is not None:
        parts.append(f"相关度：{row.relevance}")
    return "；".join(parts)


def _paper_heading(paper: Paper) -> str:
    return _inline(paper.title) or "无标题"


def _paper_meta_line(paper: Paper) -> str:
    authors = "、".join(parse_authors_json(paper.authors_json)) or "未知作者"
    year = str(paper.year) if paper.year is not None else "未知年份"
    return f"{authors}，{year}"


def _append_matrix(lines: list[str], matrix: ReviewMatrixEntry | None) -> None:
    if matrix is None:
        return
    rows = [(label, _inline(getattr(matrix, field))) for field, label in MATRIX_FIELD_LABELS]
    rows = [(label, value) for label, value in rows if value]
    if not rows:
        return
    lines.extend(["", "### 审阅矩阵"])
    for label, value in rows:
        lines.append(f"- {label}：{value}")


def _append_notes(lines: list[str], notes: list[PaperNote]) -> None:
    if not notes:
        return
    lines.extend(["", "### 笔记"])
    for note in notes:
        tags = _tags(note.tags_json)
        suffix = f"（{', '.join(tags)}）" if tags else ""
        kind = NOTE_KIND_LABELS.get(note.kind, note.kind)
        lines.append(f"- {kind}{suffix}：{_inline(note.content)}")


def _append_excerpts(lines: list[str], excerpts: list[PaperExcerpt]) -> None:
    if not excerpts:
        return
    lines.extend(["", "### 摘录"])
    for excerpt in excerpts:
        meta: list[str] = []
        if excerpt.page is not None:
            meta.append(f"第 {excerpt.page} 页")
        if excerpt.section:
            meta.append(_inline(excerpt.section))
        tags = _tags(excerpt.tags_json)
        if tags:
            meta.append(", ".join(tags))
        if meta:
            lines.append(f"- {' · '.join(meta)}")
        for row in str(excerpt.quote).strip().splitlines():
            lines.append(f"> {row}")
        if excerpt.note:
            lines.append(f"  - 说明：{_inline(excerpt.note)}")


def export_thesis_markdown(
    session: Session,
    *,
    project_id: int | None = None,
    chapter_id: int | None = None,
) -> str:
    scope, links = _scope_links(session, project_id, chapter_id)
    by_paper: dict[int, list[PaperLink]] = defaultdict(list)
    for link in links:
        by_paper[link.paper_id].append(link)

    paper_ids = list(by_paper)
    papers = (
        session.exec(select(Paper).where(Paper.is_deleted == False, Paper.id.in_(paper_ids))).all()  # noqa: E712
        if paper_ids
        else []
    )
    papers = sorted(papers, key=lambda paper: (_paper_heading(paper).lower(), paper.id or 0))

    lines = [
        "# 论文规划素材包",
        "",
        f"- 范围：{scope}",
        f"- 论文数：{len(papers)}",
        "",
    ]
    if not papers:
        lines.append("暂无论文链接。")
        return "\n".join(lines).rstrip() + "\n"

    for paper in papers:
        paper_id = paper.id or 0
        lines.extend([f"## {_paper_heading(paper)}", ""])
        lines.append(f"- 引用：{('@' + paper.citation_key) if paper.citation_key else '未设置'}")
        lines.append(f"- 作者年份：{_paper_meta_line(paper)}")
        if paper.venue:
            lines.append(f"- 来源：{_inline(paper.venue)}")
        if paper.doi:
            lines.append(f"- DOI：{_inline(paper.doi)}")
        if paper.arxiv_id:
            lines.append(f"- arXiv：{_inline(paper.arxiv_id)}")

        for link in sorted(by_paper[paper_id], key=lambda row: (row.chapter_id is None, row.role, row.id or 0)):
            role = ROLE_LABELS.get(link.role, link.role)
            note = f"；说明：{_inline(link.note)}" if link.note else ""
            lines.append(f"- 角色：{role}；目标：{_target_label(session, link)}{note}")

        state = session.exec(select(PaperReadingState).where(PaperReadingState.paper_id == paper_id)).first()
        lines.append(f"- {_state_line(state)}")

        matrix = session.exec(select(ReviewMatrixEntry).where(ReviewMatrixEntry.paper_id == paper_id)).first()
        notes = session.exec(
            select(PaperNote).where(PaperNote.paper_id == paper_id).order_by(PaperNote.updated_at.desc())
        ).all()
        excerpts = session.exec(
            select(PaperExcerpt)
            .where(PaperExcerpt.paper_id == paper_id)
            .order_by(PaperExcerpt.page.is_(None), PaperExcerpt.page, PaperExcerpt.updated_at.desc())
        ).all()
        _append_matrix(lines, matrix)
        _append_notes(lines, notes)
        _append_excerpts(lines, excerpts)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
