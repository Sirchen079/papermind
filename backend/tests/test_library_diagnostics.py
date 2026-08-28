import json

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import AnalysisRun, Concept, Paper, PaperChunk, PaperConcept, Summary


def _paper_row(rows: list[dict], title: str) -> dict:
    return next(row for row in rows if row["paper"]["title"] == title)


def _issue_ids(row: dict) -> set[str]:
    return {issue["id"] for issue in row["issues"]}


def test_library_diagnostics_empty_library(client):
    res = client.get("/api/library/diagnostics")

    assert res.status_code == 200
    body = res.json()
    assert body["summary"] == {
        "total": 0,
        "healthy": 0,
        "warning": 0,
        "critical": 0,
        "needs_action": 0,
    }
    assert body["papers"] == []


def test_library_diagnostics_reports_import_quality_and_ignores_deleted(client):
    with Session(get_engine()) as session:
        broken = Paper(
            source="pdf",
            title="Broken PDF",
            parse_confidence=0.31,
        )
        partial = Paper(
            source="pdf",
            title="Partial Paper",
            citation_key="partial2026",
            abstract="Has an abstract.",
            full_text="Has full text.",
            parse_confidence=0.92,
        )
        healthy = Paper(
            source="pdf",
            title="Healthy Paper",
            citation_key="healthy2026",
            abstract="Has an abstract.",
            full_text="Has full text.",
            parse_confidence=0.96,
        )
        deleted = Paper(source="pdf", title="Deleted Paper", is_deleted=True)
        session.add(broken)
        session.add(partial)
        session.add(healthy)
        session.add(deleted)
        session.commit()
        session.refresh(broken)
        session.refresh(partial)
        session.refresh(healthy)
        session.add(
            AnalysisRun(
                paper_id=broken.id,
                status="failed",
                error="upstream returned 500",
            )
        )
        session.add(Summary(paper_id=partial.id, content_json=json.dumps({"problem": "P"})))
        session.add(Summary(paper_id=healthy.id, content_json=json.dumps({"problem": "P"})))
        concept = Concept(name="RAG", normalized_key="rag", type="method")
        session.add(concept)
        session.commit()
        session.refresh(concept)
        session.add(PaperConcept(paper_id=healthy.id, concept_id=concept.id))
        session.add(PaperChunk(paper_id=healthy.id, ordinal=0, text="chunk", embedding=b"123", embedding_model="bge"))
        session.commit()

    res = client.get("/api/library/diagnostics")

    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["total"] == 3
    assert body["summary"]["critical"] == 1
    assert body["summary"]["warning"] == 1
    assert body["summary"]["healthy"] == 1
    assert body["issue_counts"]["missing_text"] == 1
    assert body["issue_counts"]["analysis_failed"] == 1
    assert body["issue_counts"]["missing_citation_key"] == 1
    assert body["issue_counts"]["not_indexed"] == 2

    broken_row = _paper_row(body["papers"], "Broken PDF")
    assert broken_row["severity"] == "critical"
    assert {"missing_text", "low_parse_confidence", "analysis_failed", "missing_citation_key"}.issubset(
        _issue_ids(broken_row)
    )
    assert "upstream returned 500" in next(
        issue for issue in broken_row["issues"] if issue["id"] == "analysis_failed"
    )["detail"]

    partial_row = _paper_row(body["papers"], "Partial Paper")
    assert partial_row["severity"] == "warning"
    assert {"missing_concepts", "not_indexed"}.issubset(_issue_ids(partial_row))

    healthy_row = _paper_row(body["papers"], "Healthy Paper")
    assert healthy_row["severity"] == "ok"
    assert healthy_row["issues"] == []
    assert "Deleted Paper" not in [row["paper"]["title"] for row in body["papers"]]


def test_library_diagnostics_repair_generates_unique_citation_keys(client):
    with Session(get_engine()) as session:
        first = Paper(source="manual", title="Graph Retrieval", authors_json='["Alice Wang"]', year=2026)
        second = Paper(source="manual", title="Graph Retrieval", authors_json='["Alice Wang"]', year=2026)
        existing = Paper(
            source="manual",
            title="Already Keyed",
            authors_json='["Alice Wang"]',
            year=2026,
            citation_key="alicewang2026graphretrieval",
        )
        session.add(first)
        session.add(second)
        session.add(existing)
        session.commit()

    res = client.post("/api/library/diagnostics/repair", json={"action": "citation_keys"})

    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "citation_keys"
    assert body["configured"] is True
    assert body["processed"] == 2
    assert body["changed"] == 2
    with Session(get_engine()) as session:
        papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
        keys = [paper.citation_key for paper in papers]
    assert all(keys)
    assert len(keys) == len(set(keys))
    diagnostics = client.get("/api/library/diagnostics").json()
    assert diagnostics["issue_counts"].get("missing_citation_key", 0) == 0


def test_library_diagnostics_repair_reanalyze_reports_missing_llm(client):
    with Session(get_engine()) as session:
        session.add(Paper(source="manual", title="Needs AI", abstract="Has enough text."))
        session.commit()

    res = client.post("/api/library/diagnostics/repair", json={"action": "reanalyze"})

    assert res.status_code == 200
    body = res.json()
    assert body == {
        "action": "reanalyze",
        "configured": False,
        "processed": 0,
        "changed": 0,
        "failed": [],
        "error": "未配置可用的 LLM，请先在设置中配置对话模型。",
    }
