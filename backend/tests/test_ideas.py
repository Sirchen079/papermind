"""Idea entity: lifecycle, paper links, API (P9.1) + relation analysis (P9.2)."""

import json
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Idea, IdeaPaperLink, Paper, Project


def _paper(session: Session, title: str) -> Paper:
    paper = Paper(source="manual", title=title)
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _create_idea(client, **overrides) -> dict:
    payload = {"title": "用图神经网络做文献自动分类", **overrides}
    res = client.post("/api/ideas", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_idea_crud_and_soft_delete(client):
    created = _create_idea(client, hypothesis="GNN 结构能提升分类精度", priority="high", origin="manual")
    assert created["status"] == "proposed"
    assert created["priority"] == "high"
    assert created["hypothesis"].startswith("GNN")

    listed = client.get("/api/ideas").json()
    assert [i["id"] for i in listed] == [created["id"]]

    patched = client.patch(f"/api/ideas/{created['id']}", json={"content": "# 计划\n先做基线实验。"}).json()
    assert patched["content"].startswith("# 计划")

    assert client.delete(f"/api/ideas/{created['id']}").status_code == 204
    assert client.get("/api/ideas").json() == []
    assert client.get(f"/api/ideas/{created['id']}").status_code == 404
    with Session(get_engine()) as session:
        assert session.get(Idea, created["id"]).is_deleted is True


def test_idea_state_machine_allows_chain_and_direct_drop(client):
    idea = _create_idea(client)

    # Full happy chain: proposed → refining → testing → adopted.
    for status in ("refining", "testing", "adopted"):
        res = client.patch(f"/api/ideas/{idea['id']}", json={"status": status})
        assert res.status_code == 200, res.text
        assert res.json()["status"] == status
    assert res.json()["closed_at"] is not None

    # proposed → dropped is the cheap kill.
    other = _create_idea(client, title="另一个想法")
    res = client.patch(f"/api/ideas/{other['id']}", json={"status": "dropped"})
    assert res.status_code == 200
    assert res.json()["closed_at"] is not None


def test_idea_state_machine_rejects_illegal_jumps_with_structured_error(client):
    idea = _create_idea(client)

    res = client.patch(f"/api/ideas/{idea['id']}", json={"status": "adopted"})
    assert res.status_code == 422
    assert "refining" in res.json()["detail"]  # names allowed targets

    res = client.patch(f"/api/ideas/{idea['id']}", json={"status": "testing"})
    assert res.status_code == 422

    # refining → dropped is NOT allowed (only proposed/testing may drop).
    assert client.patch(f"/api/ideas/{idea['id']}", json={"status": "refining"}).status_code == 200
    res = client.patch(f"/api/ideas/{idea['id']}", json={"status": "dropped"})
    assert res.status_code == 422

    # Invalid enum values are rejected too.
    assert client.patch(f"/api/ideas/{idea['id']}", json={"status": "bogus"}).status_code == 422
    assert client.patch(f"/api/ideas/{idea['id']}", json={"priority": "urgent"}).status_code == 422
    assert client.post("/api/ideas", json={"title": "x", "origin": "dream"}).status_code == 422


def test_idea_paper_links_multi_role_and_idempotent(client):
    with Session(get_engine()) as session:
        paper = _paper(session, "Evidence Paper")

    idea = _create_idea(client, papers=[{"paper_id": paper.id, "role": "basis"}])
    assert idea["papers"] == [
        {"paper_id": paper.id, "title": "Evidence Paper", "role": "basis", "note": None}
    ]

    # Same paper in a second role: allowed.
    res = client.post(
        f"/api/ideas/{idea['id']}/papers", json={"paper_id": paper.id, "role": "contrast"}
    )
    assert res.status_code == 201
    # Same (paper, role) again: idempotent, no duplicate row.
    assert client.post(
        f"/api/ideas/{idea['id']}/papers", json={"paper_id": paper.id, "role": "contrast"}
    ).status_code == 201
    with Session(get_engine()) as session:
        rows = session.exec(
            select(IdeaPaperLink).where(IdeaPaperLink.idea_id == idea["id"])
        ).all()
        assert len(rows) == 2

    # Invalid role / missing paper.
    assert client.post(
        f"/api/ideas/{idea['id']}/papers", json={"paper_id": paper.id, "role": "backup"}
    ).status_code == 422
    assert client.post(
        f"/api/ideas/{idea['id']}/papers", json={"paper_id": 99999, "role": "support"}
    ).status_code == 404

    # Detach one role; the other stays.
    assert (
        client.delete(f"/api/ideas/{idea['id']}/papers/{paper.id}/contrast").status_code == 204
    )
    detail = client.get(f"/api/ideas/{idea['id']}").json()
    assert [p["role"] for p in detail["papers"]] == ["basis"]


def test_idea_project_anchor_validated(client):
    with Session(get_engine()) as session:
        project = Project(name="研究论文方向")
        session.add(project)
        session.commit()
        project_id = project.id

    res = _create_idea(client, project_id=project_id)
    assert res["project_id"] == project_id

    assert client.post("/api/ideas", json={"title": "x", "project_id": 99999}).status_code == 404

    patched = client.patch(
        f"/api/ideas/{res['id']}", json={"project_id": None}
    ).json()
    assert patched["project_id"] is None


def test_idea_filters(client):
    _create_idea(client, title="想法 A", priority="high")
    _create_idea(client, title="想法 B", priority="low")

    high = client.get("/api/ideas", params={"priority": "high"}).json()
    assert [i["title"] for i in high] == ["想法 A"]
    low = client.get("/api/ideas", params={"priority": "low"}).json()
    assert [i["title"] for i in low] == ["想法 B"]


# ---------------------------------------------------------------------------
# P9.2 — analyze_relations (ingest AI relation analysis)
# ---------------------------------------------------------------------------

from unittest.mock import patch

from app.ai_ops.relations import analyze_relations
from app.models import Concept, Model, PaperConcept, Provider, Suggestion, Summary
from app.providers.client import CompletionResult


def _seed_chat_provider():
    with Session(get_engine()) as s:
        provider = Provider(name="oai", type="openai_chat", enabled=True)
        s.add(provider)
        s.commit()
        s.refresh(provider)
        s.add(Model(provider_id=provider.id, model_id="gpt-4o", role_default="chat"))
        s.commit()


def _completion(content: str) -> CompletionResult:
    return CompletionResult(content=content, prompt_tokens=1, completion_tokens=1, total_tokens=2)


def _paper_with_concept(session: Session, title: str, concept_name: str, summary: dict | None = None):
    paper = _paper(session, title)
    normalized_key = concept_name.lower()
    concept = session.exec(
        select(Concept).where(Concept.normalized_key == normalized_key)
    ).first()
    if concept is None:  # normalized_key is unique — reuse across fixtures
        concept = Concept(name=concept_name, normalized_key=normalized_key)
        session.add(concept)
        session.commit()
        session.refresh(concept)
    session.add(PaperConcept(paper_id=paper.id, concept_id=concept.id, weight=1.0))
    if summary:
        session.add(Summary(paper_id=paper.id, content_json=json.dumps(summary, ensure_ascii=False)))
    session.commit()
    session.refresh(paper)
    return paper


def test_analyze_relations_creates_conflict_and_combination_suggestions(client):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        a = _paper_with_concept(session, "新方法论文", "图神经网络", {"method": "对比学习"})
        b = _paper_with_concept(session, "旧方法论文", "图神经网络", {"method": "监督学习"})
        a_id, b_id = a.id, b.id

    llm = json.dumps(
        {
            "relations": [
                {"related_paper_id": b_id, "type": "method_conflict", "reason": "监督 vs 对比，结论相反"},
                {"related_paper_id": b_id, "type": "combination", "reason": "可以混合两种训练目标"},
            ]
        },
        ensure_ascii=False,
    )
    with patch("app.providers.client.ProviderClient.complete", return_value=_completion(llm)):
        with Session(get_engine()) as session:
            paper = session.get(Paper, a_id)
            created = analyze_relations(session, paper)
    assert created == 2

    with Session(get_engine()) as session:
        rows = session.exec(
            select(Suggestion).where(Suggestion.paper_id == min(a_id, b_id))
        ).all()
        kinds = {r.kind for r in rows}
        assert kinds == {"method_conflict", "combination"}
        conflict = next(r for r in rows if r.kind == "method_conflict")
        assert "存在方法/结论冲突" in conflict.title
        detail = json.loads(conflict.detail_json)
        assert detail["reason"].startswith("监督 vs")

    # Idempotent: re-running never duplicates.
    with patch("app.providers.client.ProviderClient.complete", return_value=_completion(llm)):
        with Session(get_engine()) as session:
            paper = session.get(Paper, a_id)
            assert analyze_relations(session, paper) == 0


def test_analyze_relations_degrades_on_llm_failure_and_bad_payload(client):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        a = _paper_with_concept(session, "论文甲", "检索增强")
        _paper_with_concept(session, "论文乙", "检索增强")
        a_id = a.id

    with Session(get_engine()) as session:
        paper = session.get(Paper, a_id)
        with patch(
            "app.providers.client.ProviderClient.complete",
            side_effect=RuntimeError("provider down"),
        ):
            assert analyze_relations(session, paper) == 0
        with patch(
            "app.providers.client.ProviderClient.complete",
            return_value=_completion("not json at all"),
        ):
            assert analyze_relations(session, paper) == 0

    with Session(get_engine()) as session:
        assert session.exec(select(Suggestion).where(Suggestion.kind == "method_conflict")).all() == []


def test_analyze_relations_skips_without_provider_or_neighbors(client):
    # No provider configured at all → silent skip.
    with Session(get_engine()) as session:
        a = _paper_with_concept(session, "孤立论文", "孤立概念")
        assert analyze_relations(session, a) == 0


def test_ingest_triggers_relation_analysis(client):
    """Full ingest path: mocked LLM produces summary + concepts + relations."""
    _seed_chat_provider()
    # A pre-existing paper sharing a concept with the new one gives the
    # relation pass a neighbor (RAG is off in tests → concept fallback).
    with Session(get_engine()) as session:
        _paper_with_concept(session, "Existing Neighbor Paper", "对比学习")

    bibtex = (
        "@article{a, title = {Ingest Relation Paper}, author = {A}, year = {2024}, "
        "abstract = {An abstract long enough to trigger AI analysis.}}"
    )
    with patch(
        "app.providers.client.ProviderClient.complete",
        side_effect=[
            _completion('{"problem":"P","method":"M","dataset":"D","results":"R","limitations":"L"}'),
            _completion('[{"name": "对比学习", "type": "method", "evidence": "对比训练"}]'),
            _completion('{"relations": []}'),
        ],
    ) as mocked:
        res = client.post("/api/papers/bibtex", json={"bibtex": bibtex})
    assert res.status_code == 200
    # Three LLM roles were consulted: summarize, concepts, relations.
    assert mocked.call_count == 3
    with Session(get_engine()) as session:
        assert session.exec(select(Suggestion).where(Suggestion.kind == "combination")).all() == []


# ---------------------------------------------------------------------------
# P9.3 — deterministic research gaps
# ---------------------------------------------------------------------------

from app.models import PaperReadingState, ReviewMatrixEntry


def _year(session: Session, paper_id: int, year: int | None) -> None:
    paper = session.get(Paper, paper_id)
    paper.year = year
    session.add(paper)
    session.commit()


def test_research_gaps_three_sources_deterministic(client):
    from datetime import datetime, timezone

    current_year = datetime.now(timezone.utc).year
    with Session(get_engine()) as session:
        # (a) matrix gap: two papers share a concept and both have limitations.
        m1 = _paper_with_concept(session, "矩阵论文一", "知识蒸馏", None)
        m2 = _paper_with_concept(session, "矩阵论文二", "知识蒸馏", None)
        session.add(ReviewMatrixEntry(paper_id=m1.id, limitations="仅在图像任务验证", future_work=""))
        session.add(ReviewMatrixEntry(paper_id=m2.id, limitations="", future_work="扩展到图数据"))
        session.commit()

        # (b) stale hub: 3 old papers around one concept, all years old.
        stale_ids = []
        for i in range(3):
            p = _paper_with_concept(session, f"旧主题论文{i}", "专家系统")
            _year(session, p.id, 1990 + i)
            stale_ids.append(p.id)
        # active hub (should NOT appear): recent years.
        for i in range(3):
            p = _paper_with_concept(session, f"新主题论文{i}", "大语言模型")
            _year(session, p.id, current_year)
        # fresh concept with <3 papers (no hub).
        _paper_with_concept(session, "单篇概念论文", "单篇概念")

        # (c) off-topic gem: rating 5, relevance 1.
        gem = _paper(session, "高质量但离题论文")
        session.add(PaperReadingState(paper_id=gem.id, rating=5, relevance=1))
        session.commit()

        matrix_ids = sorted([m1.id, m2.id])
        stale_sorted = sorted(stale_ids)
        gem_id = gem.id

    body = client.get("/api/research-gaps").json()
    by_type: dict[str, list[dict]] = {}
    for gap in body:
        by_type.setdefault(gap["type"], []).append(gap)

    matrix = by_type.get("matrix_open_question", [])
    hit = next(g for g in matrix if "知识蒸馏" in g["title"])
    assert hit["paper_ids"] == matrix_ids
    assert "仅在图像任务验证" in hit["rationale"]
    assert "扩展到图数据" in hit["rationale"]

    stale = by_type.get("stale_hub", [])
    hub = next(g for g in stale if "专家系统" in g["title"])
    assert hub["paper_ids"] == stale_sorted
    assert not any("大语言模型" in g["title"] for g in stale)  # active theme excluded

    gems = by_type.get("off_topic_gem", [])
    assert [g["paper_ids"] for g in gems] == [[gem_id]]

    # Deterministic: same request, same output.
    assert client.get("/api/research-gaps").json() == body


# ---------------------------------------------------------------------------
# P9.5 — ideas in JSON export
# ---------------------------------------------------------------------------

def test_export_json_includes_ideas_and_links(client):
    from app.archive.service import export_json

    with Session(get_engine()) as session:
        paper = _paper(session, "Idea Evidence Paper")
        idea = Idea(title="导出测试想法", content="内容", status="refining", origin="gap")
        session.add(idea)
        session.commit()
        session.refresh(idea)
        session.add(IdeaPaperLink(idea_id=idea.id, paper_id=paper.id, role="support"))
        deleted = Idea(title="已删除想法")
        session.add(deleted)
        session.commit()
        session.refresh(deleted)
        deleted.is_deleted = True
        session.add(deleted)
        session.commit()
        idea_id = idea.id

    with Session(get_engine()) as session:
        exported = export_json(session)

    ideas = exported["ideas"]
    assert [i["id"] for i in ideas] == [idea_id]
    assert ideas[0]["status"] == "refining"
    assert exported["idea_paper_links"] and exported["idea_paper_links"][0]["role"] == "support"
