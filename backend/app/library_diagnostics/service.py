from collections import Counter
import re

from sqlmodel import Session, select

from app.models import AnalysisRun, Paper, PaperChunk, PaperConcept, Summary
from app.models.base import utcnow
from app.models.paper import parse_authors_json

LOW_PARSE_CONFIDENCE = 0.55
UNCONFIGURED_LLM_ERROR = "未配置可用的 LLM，请先在设置中配置对话模型。"


def _issue(issue_id: str, severity: str, label: str, detail: str, action: str, route: str) -> dict:
    return {
        "id": issue_id,
        "severity": severity,
        "label": label,
        "detail": detail,
        "action": action,
        "route": route,
    }


def _latest_analysis_by_paper(session: Session) -> dict[int, AnalysisRun]:
    rows = session.exec(select(AnalysisRun).order_by(AnalysisRun.id)).all()
    out: dict[int, AnalysisRun] = {}
    for row in rows:
        out[row.paper_id] = row
    return out


def _ids_with_summary(session: Session, active_ids: set[int]) -> set[int]:
    return {
        row.paper_id
        for row in session.exec(select(Summary)).all()
        if row.paper_id in active_ids and row.content_json
    }


def _ids_with_concepts(session: Session, active_ids: set[int]) -> set[int]:
    return {
        row.paper_id
        for row in session.exec(select(PaperConcept)).all()
        if row.paper_id in active_ids
    }


def _ids_with_index(session: Session, active_ids: set[int]) -> set[int]:
    return {
        row.paper_id
        for row in session.exec(select(PaperChunk)).all()
        if row.paper_id in active_ids and row.embedding
    }


def _severity(issues: list[dict]) -> str:
    if any(issue["severity"] == "critical" for issue in issues):
        return "critical"
    if issues:
        return "warning"
    return "ok"


def _paper_public(paper: Paper) -> dict:
    return {
        "id": paper.id,
        "title": paper.title,
        "authors": parse_authors_json(paper.authors_json),
        "year": paper.year,
        "venue": paper.venue,
        "source": paper.source,
        "citation_key": paper.citation_key,
    }


def library_diagnostics(session: Session) -> dict:
    papers = session.exec(select(Paper).where(Paper.is_deleted == False).order_by(Paper.updated_at.desc())).all()  # noqa: E712
    active_ids = {paper.id for paper in papers if paper.id is not None}
    summary_ids = _ids_with_summary(session, active_ids)
    concept_ids = _ids_with_concepts(session, active_ids)
    indexed_ids = _ids_with_index(session, active_ids)
    analyses = _latest_analysis_by_paper(session)

    rows: list[dict] = []
    issue_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()

    for paper in papers:
        pid = paper.id
        issues: list[dict] = []
        has_text = bool(paper.abstract or paper.full_text)
        if not has_text:
            issues.append(
                _issue(
                    "missing_text",
                    "critical",
                    "缺少可用文本",
                    "这篇论文没有摘要或全文，AI 摘要、RAG 问答和审阅矩阵草稿都缺少依据。",
                    "补充摘要或重新导入 PDF",
                    "library",
                )
            )
        if paper.parse_confidence is not None and paper.parse_confidence < LOW_PARSE_CONFIDENCE:
            issues.append(
                _issue(
                    "low_parse_confidence",
                    "critical",
                    "PDF 解析质量低",
                    f"当前解析置信度为 {paper.parse_confidence:.2f}，正文可能缺页、乱码或结构混乱。",
                    "检查 PDF 或补充元数据",
                    "library",
                )
            )
        latest = analyses.get(pid)
        if latest and latest.status == "failed":
            detail = f"最近一次 AI 分析失败：{latest.error or '无错误详情'}"
            issues.append(
                _issue(
                    "analysis_failed",
                    "critical",
                    "AI 分析失败",
                    detail,
                    "重试分析",
                    "library",
                )
            )
        if pid not in summary_ids:
            issues.append(
                _issue(
                    "missing_summary",
                    "warning",
                    "缺少 AI 摘要",
                    "论文还没有结构化摘要，后续写综述和审阅矩阵会缺少基础材料。",
                    "生成摘要",
                    "library",
                )
            )
        if pid not in concept_ids:
            issues.append(
                _issue(
                    "missing_concepts",
                    "warning",
                    "缺少概念关系",
                    "这篇论文尚未连接到概念图谱，图谱检索和主题聚类价值会下降。",
                    "重新分析概念",
                    "library",
                )
            )
        if pid not in indexed_ids:
            issues.append(
                _issue(
                    "not_indexed",
                    "warning",
                    "未进入向量索引",
                    "RAG 问答无法检索到这篇论文的内容。",
                    "重建索引",
                    "settings",
                )
            )
        if not paper.citation_key:
            issues.append(
                _issue(
                    "missing_citation_key",
                    "warning",
                    "缺少引用键",
                    "导出 BibTeX 或写作引用时缺少稳定 citation key。",
                    "补充 citation key",
                    "library",
                )
            )

        severity = _severity(issues)
        severity_counts[severity] += 1
        for issue in issues:
            issue_counts[issue["id"]] += 1
        rows.append(
            {
                "paper": _paper_public(paper),
                "severity": severity,
                "issues": issues,
                "signals": {
                    "has_text": has_text,
                    "has_summary": pid in summary_ids,
                    "has_concepts": pid in concept_ids,
                    "indexed": pid in indexed_ids,
                    "parse_confidence": paper.parse_confidence,
                    "analysis_status": latest.status if latest else None,
                },
            }
        )

    return {
        "summary": {
            "total": len(papers),
            "healthy": severity_counts["ok"],
            "warning": severity_counts["warning"],
            "critical": severity_counts["critical"],
            "needs_action": severity_counts["warning"] + severity_counts["critical"],
        },
        "issue_counts": dict(issue_counts),
        "papers": rows,
    }


def repair_library_diagnostics(session: Session, action: str) -> dict:
    if action == "citation_keys":
        return _repair_citation_keys(session)
    if action == "reanalyze":
        return _repair_reanalyze(session)
    raise ValueError("unsupported diagnostics repair action")


def _repair_citation_keys(session: Session) -> dict:
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    used = {paper.citation_key for paper in papers if paper.citation_key}
    targets = [paper for paper in papers if not paper.citation_key]
    for paper in targets:
        paper.citation_key = _unique_citation_key(paper, used)
        paper.updated_at = utcnow()
        used.add(paper.citation_key)
        session.add(paper)
    session.commit()
    return {
        "action": "citation_keys",
        "configured": True,
        "processed": len(targets),
        "changed": len(targets),
        "failed": [],
        "error": None,
    }


def _repair_reanalyze(session: Session) -> dict:
    from app.ingestion.service import analyze_paper
    from app.providers.selection import pick_llm

    picked = pick_llm(session, "summary")
    if picked is None:
        return {
            "action": "reanalyze",
            "configured": False,
            "processed": 0,
            "changed": 0,
            "failed": [],
            "error": UNCONFIGURED_LLM_ERROR,
        }

    client, provider, model_id = picked
    targets = _reanalyze_targets(session)
    failed = []
    for paper in targets:
        analyze_paper(session, paper, client, provider, model_id)
        latest = _latest_analysis_by_paper(session).get(paper.id)
        if latest and latest.status == "failed":
            failed.append({"paper_id": paper.id, "title": paper.title, "error": latest.error})
    return {
        "action": "reanalyze",
        "configured": True,
        "processed": len(targets),
        "changed": len(targets) - len(failed),
        "failed": failed,
        "error": None,
    }


def _reanalyze_targets(session: Session) -> list[Paper]:
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    active_ids = {paper.id for paper in papers if paper.id is not None}
    summary_ids = _ids_with_summary(session, active_ids)
    concept_ids = _ids_with_concepts(session, active_ids)
    analyses = _latest_analysis_by_paper(session)
    targets: list[Paper] = []
    for paper in papers:
        if not (paper.abstract or paper.full_text):
            continue
        latest = analyses.get(paper.id)
        if paper.id not in summary_ids or paper.id not in concept_ids or (latest and latest.status == "failed"):
            targets.append(paper)
    return targets


def _slug(value: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "", value or "").lower()
    return text[:32]


def _unique_citation_key(paper: Paper, used: set[str]) -> str:
    authors = parse_authors_json(paper.authors_json)
    author = _slug(authors[0] if authors else None)
    title = _slug(paper.title)
    base = f"{author or 'paper'}{paper.year or ''}{title or paper.id or 'work'}"
    base = base[:48] or f"paper{paper.id or 'work'}"
    key = base
    suffix = 2
    while key in used:
        key = f"{base}{suffix}"
        suffix += 1
    return key
