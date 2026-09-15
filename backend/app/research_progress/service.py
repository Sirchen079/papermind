from collections import Counter

from sqlmodel import Session, select

from app.library_diagnostics.service import library_diagnostics
from app.models import Chapter, Paper, PaperLink, PaperReadingState, Project, ReviewMatrixEntry

STATUSES = ("unread", "queued", "reading", "read", "skipped")

PRIORITY_LABELS = {
    "high": "优先处理",
    "normal": "建议推进",
    "low": "持续维护",
}


def _action(action_id: str, label: str, detail: str, route: str, priority: str) -> dict:
    return {
        "id": action_id,
        "label": label,
        "detail": detail,
        "route": route,
        "priority": priority,
    }


def research_progress(session: Session) -> dict:
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    active_ids = {paper.id for paper in papers if paper.id is not None}
    states = [
        row
        for row in session.exec(select(PaperReadingState)).all()
        if row.paper_id in active_ids
    ]
    state_by_paper = {row.paper_id: row for row in states}
    matrix_paper_ids = {
        row.paper_id
        for row in session.exec(select(ReviewMatrixEntry)).all()
        if row.paper_id in active_ids
    }
    links = [
        row
        for row in session.exec(select(PaperLink)).all()
        if row.paper_id in active_ids
    ]
    linked_paper_ids = {row.paper_id for row in links}
    projects = session.exec(select(Project)).all()
    chapters = session.exec(select(Chapter)).all()
    diagnostics = library_diagnostics(session)

    status_counts = Counter({status: 0 for status in STATUSES})
    for paper in papers:
        row = state_by_paper.get(paper.id)
        status_counts[row.status if row else "unread"] += 1

    read_ids = {
        paper.id
        for paper in papers
        if (state_by_paper.get(paper.id).status if state_by_paper.get(paper.id) else "unread") == "read"
    }
    read_without_matrix = len(read_ids - matrix_paper_ids)
    read_unlinked = len(read_ids - linked_paper_ids)

    reading = {
        "total_papers": len(papers),
        "status_counts": {status: status_counts[status] for status in STATUSES},
        "high_priority": sum(1 for row in states if row.priority == "high"),
        "high_relevance": sum(1 for row in states if (row.relevance or 0) >= 4),
        "review_matrices": len(matrix_paper_ids),
        "read_without_matrix": read_without_matrix,
    }
    writing = {
        "projects": len(projects),
        "chapters": len(chapters),
        "linked_papers": len(linked_paper_ids),
        "read_unlinked_papers": read_unlinked,
        "draft_chapters": sum(1 for chapter in chapters if chapter.status == "draft"),
        "review_chapters": sum(1 for chapter in chapters if chapter.status == "review"),
        "done_chapters": sum(1 for chapter in chapters if chapter.status == "done"),
    }
    quality = diagnostics["summary"]
    actions = _next_actions(reading, writing, quality)
    return {
        "reading": reading,
        "writing": writing,
        "quality": quality,
        "actions": actions,
    }


def export_research_progress_markdown(session: Session) -> str:
    report = research_progress(session)
    reading = report["reading"]
    writing = report["writing"]
    quality = report["quality"]
    status_counts = reading["status_counts"]

    lines = [
        "# PaperMind 科研进展报告",
        "",
        "## 阅读进度",
        f"- 论文总数：{reading['total_papers']}",
        (
            "- 未读 / 待读 / 阅读中 / 已读 / 跳过："
            f"{status_counts['unread']} / {status_counts['queued']} / {status_counts['reading']} / "
            f"{status_counts['read']} / {status_counts['skipped']}"
        ),
        f"- 高优先级：{reading['high_priority']}",
        f"- 高相关：{reading['high_relevance']}",
        f"- 审阅矩阵：{reading['review_matrices']}",
        f"- 已读但缺审阅矩阵：{reading['read_without_matrix']}",
        "",
        "## 写作组织",
        f"- 项目：{writing['projects']}",
        f"- 章节：{writing['chapters']}",
        f"- 已链接论文：{writing['linked_papers']}",
        f"- 已读但未进入写作结构：{writing['read_unlinked_papers']}",
        (
            "- 章节状态："
            f"草稿 {writing['draft_chapters']}，复审 {writing['review_chapters']}，完成 {writing['done_chapters']}"
        ),
        "",
        "## 质量诊断",
        f"- 正常：{quality['healthy']}",
        f"- 待完善：{quality['warning']}",
        f"- 严重：{quality['critical']}",
        f"- 质量待处理：{quality['needs_action']}",
        "",
        "## 下一步行动",
    ]

    for index, action in enumerate(report["actions"], start=1):
        priority = PRIORITY_LABELS.get(action["priority"], "待处理")
        lines.append(f"{index}. 【{priority}】{action['label']}")
        lines.append(f"   - {action['detail']}")

    return "\n".join(lines) + "\n"


def _next_actions(reading: dict, writing: dict, quality: dict) -> list[dict]:
    actions: list[dict] = []
    if reading["total_papers"] == 0:
        return [
            _action(
                "import_papers",
                "导入第一批核心论文",
                "建议先导入 20-50 篇与课题直接相关的论文，再开始阅读和图谱分析。",
                "library",
                "high",
            )
        ]
    if quality.get("needs_action", 0) > 0:
        actions.append(
            _action(
                "fix_library_quality",
                "处理论文质量问题",
                f"{quality['needs_action']} 篇论文存在解析、摘要、索引或引用键问题，先修复可减少后续写作返工。",
                "library",
                "high" if quality.get("critical", 0) else "normal",
            )
        )
    if reading["status_counts"]["queued"] or reading["status_counts"]["reading"]:
        actions.append(
            _action(
                "process_reading_queue",
                "推进待读和在读论文",
                f"待读 {reading['status_counts']['queued']} 篇，在读 {reading['status_counts']['reading']} 篇，优先完成高相关文献。",
                "library",
                "normal",
            )
        )
    if reading["read_without_matrix"] > 0:
        actions.append(
            _action(
                "build_review_matrix",
                "补齐已读论文审阅矩阵",
                f"{reading['read_without_matrix']} 篇已读论文还没有审阅矩阵，建议补齐问题、方法、结果和局限。",
                "library",
                "normal",
            )
        )
    if writing["projects"] == 0 or writing["chapters"] == 0:
        actions.append(
            _action(
                "create_thesis_structure",
                "建立论文项目和章节结构",
                "先建立课题/论文方向和章节框架，后续阅读材料才能持续沉淀到写作位置。",
                "library",
                "normal",
            )
        )
    elif writing["read_unlinked_papers"] > 0:
        actions.append(
            _action(
                "link_read_papers_to_thesis",
                "把已读论文挂到章节",
                f"{writing['read_unlinked_papers']} 篇已读论文还没有进入写作结构，建议链接到相关章节或课题。",
                "library",
                "normal",
            )
        )
    if not actions:
        actions.append(
            _action(
                "continue_research_loop",
                "继续阅读、提炼和写作",
                "当前关键流程已经连通，可以继续导入新论文、扩展审阅矩阵并导出写作素材。",
                "library",
                "low",
            )
        )
    return actions
