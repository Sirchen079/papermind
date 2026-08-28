from sqlmodel import Session, select

from app.models import (
    Chapter,
    Concept,
    Model,
    Paper,
    PaperChunk,
    PaperConcept,
    PaperLink,
    PaperReadingState,
    Project,
    Provider,
    ReviewMatrixEntry,
    Summary,
)


def _enabled_model_roles(session: Session) -> set[str]:
    rows = session.exec(
        select(Model, Provider).join(Provider, Model.provider_id == Provider.id).where(Provider.enabled == True)  # noqa: E712
    ).all()
    return {model.role_default for model, _provider in rows if model.role_default}


def _check(check_id: str, label: str, status: str, detail: str, action: str, route: str) -> dict:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
        "action": action,
        "route": route,
    }


def _score(checks: list[dict]) -> int:
    weights = {"done": 1.0, "warning": 0.5, "action": 0.0}
    if not checks:
        return 0
    value = sum(weights.get(item["status"], 0.0) for item in checks) / len(checks)
    return round(value * 100)


def _level(score: int, papers: int) -> str:
    if score >= 85:
        return "ready"
    if score >= 50 and papers > 0:
        return "usable"
    return "setup"


def get_readiness(session: Session) -> dict:
    roles = _enabled_model_roles(session)
    has_llm = "chat" in roles
    has_embedding = "embedding" in roles

    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    active_ids = {paper.id for paper in papers if paper.id is not None}
    chunks = [row for row in session.exec(select(PaperChunk)).all() if row.paper_id in active_ids]
    indexed_chunks = [row for row in chunks if row.embedding]
    summaries = [row for row in session.exec(select(Summary)).all() if row.paper_id in active_ids]
    concept_edges = [row for row in session.exec(select(PaperConcept)).all() if row.paper_id in active_ids]
    reading_states = [row for row in session.exec(select(PaperReadingState)).all() if row.paper_id in active_ids]
    matrix_rows = [row for row in session.exec(select(ReviewMatrixEntry)).all() if row.paper_id in active_ids]
    paper_links = [row for row in session.exec(select(PaperLink)).all() if row.paper_id in active_ids]
    projects = session.exec(select(Project)).all()
    chapters = session.exec(select(Chapter)).all()
    concepts = session.exec(select(Concept)).all()

    paper_count = len(papers)
    text_papers = sum(1 for paper in papers if paper.abstract or paper.full_text)

    checks = [
        _check(
            "llm",
            "LLM 模型",
            "done" if has_llm else "action",
            "已配置对话/总结/抽取共用 LLM。" if has_llm else "尚未配置可用于总结、抽取和对话的 LLM。",
            "配置 LLM",
            "settings",
        ),
        _check(
            "embedding",
            "向量模型",
            "done" if has_embedding else "action",
            "已配置向量模型，可建立检索索引。" if has_embedding else "尚未配置 embedding 模型，RAG 问答和相似检索不可用。",
            "配置向量模型",
            "settings",
        ),
        _check(
            "library",
            "论文库",
            "done" if paper_count > 0 else "action",
            f"已入库 {paper_count} 篇论文。" if paper_count > 0 else "论文库为空，请先导入 PDF、BibTeX、arXiv 或手动录入。",
            "导入论文",
            "library",
        ),
        _check(
            "analysis",
            "AI 摘要与概念",
            "done" if summaries else ("warning" if paper_count > 0 else "action"),
            f"已有 {len(summaries)} 篇论文生成摘要，{len(concept_edges)} 条论文-概念关系。"
            if summaries
            else ("论文已入库，但还没有摘要或概念抽取结果。" if paper_count > 0 else "导入论文并配置 LLM 后可生成摘要和概念。"),
            "重新分析论文",
            "library",
        ),
        _check(
            "rag",
            "全文检索/RAG",
            "done" if indexed_chunks else ("warning" if has_embedding and text_papers > 0 else "action"),
            f"已有 {len(indexed_chunks)} 个可检索文本块。"
            if indexed_chunks
            else (
                "已有可解析文本和向量模型，但还没有建立索引，请在设置中重建索引。"
                if has_embedding and text_papers > 0
                else "需要论文文本和 embedding 模型后才能使用检索问答。"
            ),
            "重建索引",
            "settings",
        ),
        _check(
            "graph",
            "知识图谱",
            "done" if concept_edges else ("warning" if paper_count > 0 else "action"),
            f"已有 {len(concepts)} 个概念和 {len(concept_edges)} 条论文-概念关系。"
            if concept_edges
            else ("论文库已有内容，但图谱关系还不足。" if paper_count > 0 else "导入并分析论文后可形成论文/概念图谱。"),
            "查看图谱",
            "graph",
        ),
        _check(
            "reading",
            "阅读沉淀",
            "done" if reading_states or matrix_rows else ("warning" if paper_count > 0 else "action"),
            f"已有 {len(reading_states)} 条阅读状态和 {len(matrix_rows)} 条审阅矩阵。"
            if reading_states or matrix_rows
            else ("论文已入库，但还没有阅读状态、笔记或审阅矩阵。" if paper_count > 0 else "导入论文后可开始阅读标注。"),
            "进入阅读工作区",
            "library",
        ),
        _check(
            "writing",
            "论文写作组织",
            "done" if projects and chapters and paper_links else ("warning" if projects else "action"),
            f"已有 {len(projects)} 个项目、{len(chapters)} 个章节、{len(paper_links)} 条论文写作链接。"
            if projects and chapters and paper_links
            else ("已有写作项目，但还没有把论文挂到章节。" if projects else "尚未建立课题/章节结构。"),
            "组织写作材料",
            "library",
        ),
    ]
    score = _score(checks)

    return {
        "score": score,
        "level": _level(score, paper_count),
        "summary": _summary_text(score, paper_count),
        "stats": {
            "papers": paper_count,
            "papers_with_text": text_papers,
            "summaries": len(summaries),
            "concepts": len(concepts),
            "concept_edges": len(concept_edges),
            "indexed_chunks": len(indexed_chunks),
            "reading_states": len(reading_states),
            "review_matrices": len(matrix_rows),
            "projects": len(projects),
            "chapters": len(chapters),
            "paper_links": len(paper_links),
        },
        "capabilities": {
            "llm": has_llm,
            "embedding": has_embedding,
            "library": paper_count > 0,
            "rag": bool(indexed_chunks),
            "graph": bool(concept_edges),
            "reading": bool(reading_states or matrix_rows),
            "writing": bool(projects and chapters and paper_links),
        },
        "checks": checks,
    }


def _summary_text(score: int, papers: int) -> str:
    if score >= 85:
        return "科研工作台已具备完整试用条件，可以开始用真实课题材料持续工作。"
    if papers > 0:
        return "已有基础论文库，但部分 AI、检索、图谱或写作组织能力还需要补齐。"
    return "当前仍处于首次配置阶段，请先配置模型并导入论文。"
