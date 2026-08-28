from sqlmodel import Session

from app.db.engine import get_engine
from app.models import (
    Chapter,
    Paper,
    PaperLink,
    PaperReadingState,
    Project,
    ReviewMatrixEntry,
)


def _action_ids(body: dict) -> set[str]:
    return {action["id"] for action in body["actions"]}


def test_research_progress_empty_library_starts_with_import_action(client):
    res = client.get("/api/research/progress")

    assert res.status_code == 200
    body = res.json()
    assert body["reading"]["total_papers"] == 0
    assert body["reading"]["status_counts"]["unread"] == 0
    assert body["writing"]["projects"] == 0
    assert body["quality"]["needs_action"] == 0
    assert body["actions"][0]["id"] == "import_papers"
    assert body["actions"][0]["route"] == "library"


def test_research_progress_summarizes_reading_writing_and_next_actions(client):
    with Session(get_engine()) as session:
        queued = Paper(source="manual", title="Queued Paper", abstract="text")
        read_missing_matrix = Paper(source="manual", title="Read Missing Matrix", abstract="text")
        read_linked = Paper(source="manual", title="Read Linked", abstract="text")
        broken = Paper(source="manual", title="Broken Paper")
        session.add(queued)
        session.add(read_missing_matrix)
        session.add(read_linked)
        session.add(broken)
        session.commit()
        session.refresh(queued)
        session.refresh(read_missing_matrix)
        session.refresh(read_linked)
        session.refresh(broken)
        session.add(PaperReadingState(paper_id=queued.id, status="queued", priority="high"))
        session.add(PaperReadingState(paper_id=read_missing_matrix.id, status="read", relevance=5))
        session.add(PaperReadingState(paper_id=read_linked.id, status="read", relevance=4))
        session.add(ReviewMatrixEntry(paper_id=read_linked.id, problem="P", method="M"))
        project = Project(name="硕士论文", kind="direction")
        session.add(project)
        session.commit()
        session.refresh(project)
        chapter = Chapter(project_id=project.id, title="相关工作")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        session.add(PaperLink(paper_id=read_linked.id, project_id=project.id, chapter_id=chapter.id))
        session.commit()

    res = client.get("/api/research/progress")

    assert res.status_code == 200
    body = res.json()
    assert body["reading"]["total_papers"] == 4
    assert body["reading"]["status_counts"]["queued"] == 1
    assert body["reading"]["status_counts"]["read"] == 2
    assert body["reading"]["status_counts"]["unread"] == 1
    assert body["reading"]["review_matrices"] == 1
    assert body["reading"]["read_without_matrix"] == 1
    assert body["writing"]["projects"] == 1
    assert body["writing"]["chapters"] == 1
    assert body["writing"]["linked_papers"] == 1
    assert body["writing"]["read_unlinked_papers"] == 1
    assert body["quality"]["needs_action"] >= 1
    assert {
        "fix_library_quality",
        "process_reading_queue",
        "build_review_matrix",
        "link_read_papers_to_thesis",
    }.issubset(_action_ids(body))


def test_research_progress_markdown_export_summarizes_current_workflow(client):
    with Session(get_engine()) as session:
        queued = Paper(source="manual", title="Queued Paper", abstract="text")
        read_linked = Paper(source="manual", title="Read Linked", abstract="text")
        broken = Paper(source="manual", title="Broken Paper")
        session.add(queued)
        session.add(read_linked)
        session.add(broken)
        session.commit()
        session.refresh(queued)
        session.refresh(read_linked)
        session.refresh(broken)
        session.add(PaperReadingState(paper_id=queued.id, status="queued", priority="high"))
        session.add(PaperReadingState(paper_id=read_linked.id, status="read", relevance=5))
        session.add(ReviewMatrixEntry(paper_id=read_linked.id, problem="P", method="M"))
        project = Project(name="硕士论文", kind="direction")
        session.add(project)
        session.commit()
        session.refresh(project)
        chapter = Chapter(project_id=project.id, title="相关工作", status="review")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        session.add(PaperLink(paper_id=read_linked.id, project_id=project.id, chapter_id=chapter.id))
        session.commit()

    res = client.get("/api/research/progress/markdown")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    assert "papermind-research-progress.md" in res.headers["content-disposition"]
    body = res.text
    assert "# PaperMind 科研进展报告" in body
    assert "## 阅读进度" in body
    assert "- 论文总数：3" in body
    assert "- 未读 / 待读 / 阅读中 / 已读 / 跳过：1 / 1 / 0 / 1 / 0" in body
    assert "- 高优先级：1" in body
    assert "- 审阅矩阵：1" in body
    assert "## 写作组织" in body
    assert "- 项目：1" in body
    assert "- 章节：1" in body
    assert "- 已链接论文：1" in body
    assert "- 章节状态：草稿 0，复审 1，完成 0" in body
    assert "## 质量诊断" in body
    assert "- 质量待处理：" in body
    assert "## 下一步行动" in body
    assert "处理论文质量问题" in body
