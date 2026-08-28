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

    project = client.post("/api/thesis/projects", json={"name": "硕士论文主线", "kind": "direction"})
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
    assert "范围：章节 · 硕士论文主线 / 第二章 相关工作" in body
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
