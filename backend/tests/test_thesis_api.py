from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper


def test_thesis_api_workspace_projects_chapters_and_links(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="API Thesis Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        pid = paper.id

    root = client.post("/api/thesis/projects", json={"name": "Master Thesis", "kind": "direction"})
    assert root.status_code == 201
    root_id = root.json()["id"]

    child = client.post(
        "/api/thesis/projects",
        json={"name": "Topic A", "kind": "topic", "parent_project_id": root_id},
    )
    assert child.status_code == 201
    child_id = child.json()["id"]

    chapter = client.post(f"/api/thesis/projects/{root_id}/chapters", json={"title": "Related Work"})
    assert chapter.status_code == 201
    chapter_id = chapter.json()["id"]

    project_link = client.post(
        f"/api/papers/{pid}/thesis-links",
        json={"project_id": child_id, "role": "background"},
    )
    assert project_link.status_code == 201

    chapter_link = client.post(
        f"/api/papers/{pid}/thesis-links",
        json={"chapter_id": chapter_id, "role": "evidence"},
    )
    assert chapter_link.status_code == 201

    workspace = client.get("/api/thesis/workspace")
    assert workspace.status_code == 200
    body = workspace.json()
    assert body["projects"][0]["name"] == "Master Thesis"
    assert body["papers"][0]["links"]

    assert client.patch(f"/api/thesis/projects/{child_id}", json={"status": "archived"}).status_code == 200
    assert client.patch(f"/api/thesis/chapters/{chapter_id}", json={"status": "review"}).status_code == 200
    assert client.delete(f"/api/papers/{pid}/thesis-links/{project_link.json()['id']}").status_code == 204


def test_thesis_api_rejects_deleting_non_empty_nodes(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="API Linked Thesis Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        pid = paper.id

    root = client.post("/api/thesis/projects", json={"name": "Direction", "kind": "direction"})
    assert root.status_code == 201
    root_id = root.json()["id"]

    child = client.post(
        "/api/thesis/projects",
        json={"name": "Topic", "kind": "topic", "parent_project_id": root_id},
    )
    assert child.status_code == 201

    chapter = client.post(f"/api/thesis/projects/{root_id}/chapters", json={"title": "Related Work"})
    assert chapter.status_code == 201
    chapter_id = chapter.json()["id"]

    link = client.post(
        f"/api/papers/{pid}/thesis-links",
        json={"chapter_id": chapter_id, "role": "evidence"},
    )
    assert link.status_code == 201

    project_delete = client.delete(f"/api/thesis/projects/{root_id}")
    assert project_delete.status_code == 422
    assert "child project" in project_delete.json()["detail"]

    chapter_delete = client.delete(f"/api/thesis/chapters/{chapter_id}")
    assert chapter_delete.status_code == 422
    assert "linked paper" in chapter_delete.json()["detail"]


def test_thesis_markdown_export_collects_chapter_reading_materials(client):
    from sqlmodel import Session

    from app.db.engine import get_engine
    from app.models import Paper, PaperExcerpt, PaperLink, PaperNote, PaperReadingState, ReviewMatrixEntry

    with Session(get_engine()) as session:
        paper = Paper(
            source="manual",
            citation_key="smith2026workflow",
            title="A Workflow Paper",
            authors_json='["Jane Smith", "Bo Chen"]',
            year=2026,
        )
        deleted = Paper(source="manual", title="Deleted Linked Paper", is_deleted=True)
        session.add(paper)
        session.add(deleted)
        session.commit()
        session.refresh(paper)
        session.refresh(deleted)
        pid = paper.id
        deleted_id = deleted.id

    project = client.post("/api/thesis/projects", json={"name": "科研论文主线", "kind": "direction"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    chapter = client.post(f"/api/thesis/projects/{project_id}/chapters", json={"title": "第二章 相关工作"})
    assert chapter.status_code == 201
    chapter_id = chapter.json()["id"]
    link = client.post(
        f"/api/papers/{pid}/thesis-links",
        json={"chapter_id": chapter_id, "role": "evidence", "note": "用于动机论证"},
    )
    assert link.status_code == 201

    with Session(get_engine()) as session:
        session.add(PaperLink(paper_id=deleted_id, chapter_id=chapter_id, role="evidence"))
        session.add(PaperReadingState(paper_id=pid, status="read", priority="high", relevance=5, rating=4))
        session.add(
            ReviewMatrixEntry(
                paper_id=pid,
                problem="长期阅读材料难以复用。",
                method="把论文、笔记和章节结构连接起来。",
                relation_to_thesis="支撑系统设计章节。",
            )
        )
        session.add(
            PaperNote(
                paper_id=pid,
                kind="idea",
                content="可以放在开题报告的问题动机里。",
                tags_json='["开题", "动机"]',
            )
        )
        session.add(
            PaperExcerpt(
                paper_id=pid,
                quote="A stable workflow turns reading into reusable evidence.",
                page=3,
                section="Introduction",
                note="可作为写作素材。",
                tags_json='["证据"]',
            )
        )
        session.commit()

    exported = client.get(f"/api/thesis/export/markdown?chapter_id={chapter_id}")

    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/markdown")
    body = exported.text
    assert "# 论文规划素材包" in body
    assert "范围：章节 · 科研论文主线 / 第二章 相关工作" in body
    assert "## A Workflow Paper" in body
    assert "引用：@smith2026workflow" in body
    assert "角色：证据" in body
    assert "用于动机论证" in body
    assert "阅读状态：已读；优先级：高；评分：4；相关度：5" in body
    assert "长期阅读材料难以复用。" in body
    assert "可以放在开题报告的问题动机里。" in body
    assert "> A stable workflow turns reading into reusable evidence." in body
    assert "Deleted Linked Paper" not in body


def test_thesis_markdown_export_project_scope_and_parameter_validation(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Project Scope Paper", authors_json='["Ada"]', year=2025)
        session.add(paper)
        session.commit()
        session.refresh(paper)
        pid = paper.id

    project = client.post("/api/thesis/projects", json={"name": "方向 A", "kind": "direction"})
    project_id = project.json()["id"]
    child = client.post("/api/thesis/projects", json={"name": "子课题", "parent_project_id": project_id})
    child_id = child.json()["id"]
    assert client.post(f"/api/papers/{pid}/thesis-links", json={"project_id": child_id, "role": "background"}).status_code == 201

    no_scope = client.get("/api/thesis/export/markdown")
    both_scopes = client.get(f"/api/thesis/export/markdown?project_id={project_id}&chapter_id=1")
    project_export = client.get(f"/api/thesis/export/markdown?project_id={project_id}")

    assert no_scope.status_code == 422
    assert both_scopes.status_code == 422
    assert project_export.status_code == 200
    assert "范围：项目 · 方向 A" in project_export.text
    assert "Project Scope Paper" in project_export.text
    assert "项目 · 方向 A / 子课题" in project_export.text


# ---- T8：章节草稿进入 Markdown 交付物 ----


def _seed_chapter_with_paper_and_drafts(client) -> int:
    """项目 + 章节 + 挂载论文 + 两个版本草稿（新版本后写但 created_at 更晚）。"""
    from datetime import datetime, timezone

    from app.models import ChapterDraft

    with Session(get_engine()) as session:
        paper = Paper(source="manual", citation_key="chen2027draft", title="Draft Source Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        pid = paper.id

    project = client.post("/api/thesis/projects", json={"name": "论文写作项目", "kind": "direction"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    chapter = client.post(f"/api/thesis/projects/{project_id}/chapters", json={"title": "第三章 方法综述"})
    assert chapter.status_code == 201
    chapter_id = chapter.json()["id"]
    assert (
        client.post(
            f"/api/papers/{pid}/thesis-links",
            json={"chapter_id": chapter_id, "role": "background"},
        ).status_code
        == 201
    )

    with Session(get_engine()) as session:
        session.add(
            ChapterDraft(
                chapter_id=chapter_id,
                content="旧版本内容 [@chen2027draft] 应当被替换。",
                model="old-model",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        )
        session.add(
            ChapterDraft(
                chapter_id=chapter_id,
                content="最新版本：方法综述正文，引用 [@chen2027draft] 与 [@wang2026base]。",
                model="new-model",
                created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()
    return chapter_id


def test_thesis_markdown_export_appends_latest_chapter_draft(client):
    chapter_id = _seed_chapter_with_paper_and_drafts(client)

    exported = client.get(f"/api/thesis/export/markdown?chapter_id={chapter_id}")
    assert exported.status_code == 200
    body = exported.text
    assert "## 章节草稿" in body
    assert "### 第三章 方法综述" in body
    assert "最新版本：方法综述正文，引用 [@chen2027draft] 与 [@wang2026base]。" in body
    assert "旧版本内容" not in body  # 多版本只导出最新
    assert "new-model" in body  # 保留版本信息
    assert "第三章 方法综述" in body.split("## 章节草稿")[1]


def test_thesis_markdown_export_without_drafts_keeps_original_output(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="No Draft Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        pid = paper.id

    project = client.post("/api/thesis/projects", json={"name": "无草稿项目", "kind": "direction"})
    project_id = project.json()["id"]
    chapter = client.post(f"/api/thesis/projects/{project_id}/chapters", json={"title": "绪论"})
    chapter_id = chapter.json()["id"]
    assert (
        client.post(
            f"/api/papers/{pid}/thesis-links",
            json={"chapter_id": chapter_id, "role": "related"},
        ).status_code
        == 201
    )

    exported = client.get(f"/api/thesis/export/markdown?chapter_id={chapter_id}")
    assert exported.status_code == 200
    assert "## 章节草稿" not in exported.text
    assert "No Draft Paper" in exported.text


def test_chapter_draft_markdown_download_is_unicode_safe(client):
    from sqlmodel import select

    from app.models import ChapterDraft

    chapter_id = _seed_chapter_with_paper_and_drafts(client)
    with Session(get_engine()) as session:
        drafts = session.exec(
            select(ChapterDraft).where(ChapterDraft.chapter_id == chapter_id)
        ).all()
        newest = max(drafts, key=lambda d: d.created_at)
        draft_id = newest.id

    res = client.get(f"/api/thesis/chapters/{chapter_id}/drafts/{draft_id}/markdown")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    disposition = res.headers["content-disposition"]
    assert "attachment" in disposition
    assert "filename*=UTF-8''" in disposition
    # RFC 5987：非 ASCII 文件名按 percent-encoding 放在 filename* 中。
    assert "%E7%AC%AC%E4%B8%89%E7%AB%A0" in disposition
    assert "第三章 方法综述" in res.text
    assert "[@chen2027draft]" in res.text
    assert "new-model" in res.text


def test_chapter_draft_markdown_download_rejects_mismatched_ids(client):
    chapter_id = _seed_chapter_with_paper_and_drafts(client)
    other_project = client.post("/api/thesis/projects", json={"name": "另一个项目", "kind": "direction"})
    other_chapter = client.post(
        f"/api/thesis/projects/{other_project.json()['id']}/chapters", json={"title": "别的章节"}
    )
    other_chapter_id = other_chapter.json()["id"]

    assert client.get(f"/api/thesis/chapters/{chapter_id}/drafts/999999/markdown").status_code == 404
    assert client.get(f"/api/thesis/chapters/{other_chapter_id}/drafts/1/markdown").status_code == 404
