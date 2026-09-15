"""P12 Claim-Evidence 图谱：抽取开关/幂等/降级、手动论断 CRUD、
论断关系（矛盾检测扩展）、论断图 API。LLM 全部 mock，零网络。"""

import json
from unittest.mock import patch

from sqlmodel import Session, select

from app.ai_ops.claims import analyze_claim_relations, extract_claims
from app.db.engine import get_engine, make_engine
from app.models import (
    Claim,
    ClaimRelation,
    Concept,
    Model,
    Paper,
    PaperConcept,
    Provider,
    Setting,
    Suggestion,
    Summary,
)
from app.models.paper import parse_summary_json
from app.providers.client import CompletionResult


def _completion(content: str) -> CompletionResult:
    return CompletionResult(content=content, prompt_tokens=1, completion_tokens=1, total_tokens=2)


def _seed_chat_provider() -> None:
    with Session(get_engine()) as session:
        provider = Provider(name="oai", type="openai_chat", enabled=True)
        session.add(provider)
        session.commit()
        session.refresh(provider)
        session.add(Model(provider_id=provider.id, model_id="gpt-4o", role_default="chat"))
        session.commit()


def _enable_extraction(enabled: bool) -> None:
    with Session(get_engine()) as session:
        row = session.get(Setting, "claim_extraction_enabled")
        if row is None:
            row = Setting(key="claim_extraction_enabled", value="true" if enabled else "false")
        else:
            row.value = "true" if enabled else "false"
        session.add(row)
        session.commit()


def _paper(session: Session, title: str, abstract: str | None = None) -> Paper:
    paper = Paper(source="manual", title=title, abstract=abstract)
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _paper_with_summary(session: Session, title: str, summary: dict) -> Paper:
    paper = _paper(session, title)
    session.add(Summary(paper_id=paper.id, content_json=json.dumps(summary, ensure_ascii=False)))
    session.commit()
    session.refresh(paper)
    return paper


def _paper_with_concept(session: Session, title: str, concept_name: str, claims: list[str]) -> Paper:
    """邻接发现依赖概念共现（RAG 检索在测试库为空时回退到概念共现）。"""
    paper = _paper(session, title)
    normalized_key = concept_name.lower()
    concept = session.exec(select(Concept).where(Concept.normalized_key == normalized_key)).first()
    if concept is None:
        concept = Concept(name=concept_name, normalized_key=normalized_key)
        session.add(concept)
        session.commit()
        session.refresh(concept)
    session.add(PaperConcept(paper_id=paper.id, concept_id=concept.id, weight=1.0))
    for text in claims:
        session.add(Claim(paper_id=paper.id, text=text, kind="main", source="user"))
    session.commit()
    session.refresh(paper)
    return paper


# ---------------------------------------------------------------------------
# P12.2 抽取（开关默认关）与手动论断
# ---------------------------------------------------------------------------


def test_claim_extraction_disabled_by_default(client):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        paper = _paper_with_summary(session, "默认关论文", {"results": "准确率提升 10%"})
        paper_id = paper.id

    llm = json.dumps({"claims": ["方法 A 在数据集 B 上准确率提升 10%"]}, ensure_ascii=False)
    with patch("app.providers.client.ProviderClient.complete", return_value=_completion(llm)) as mock:
        with Session(get_engine()) as session:
            paper = session.get(Paper, paper_id)
            assert extract_claims(session, paper) == 0
        mock.assert_not_called()

    with Session(get_engine()) as session:
        assert session.exec(select(Claim)).all() == []


def test_claim_extraction_enabled_idempotent_and_capped(client):
    _seed_chat_provider()
    _enable_extraction(True)
    with Session(get_engine()) as session:
        paper = _paper_with_summary(session, "抽取论文", {"results": "结论一；结论二；结论三；结论四"})
        paper_id = paper.id

    llm = json.dumps(
        {"claims": ["结论一", "  结论二  ", "", "结论一", "结论三"]},
        ensure_ascii=False,
    )
    with patch("app.providers.client.ProviderClient.complete", return_value=_completion(llm)):
        with Session(get_engine()) as session:
            paper = session.get(Paper, paper_id)
            assert extract_claims(session, paper) == 3  # 3 条去重后的论断，空串跳过

    # 幂等：完全相同的文本不重复插入
    with patch("app.providers.client.ProviderClient.complete", return_value=_completion(llm)):
        with Session(get_engine()) as session:
            paper = session.get(Paper, paper_id)
            assert extract_claims(session, paper) == 0

    with Session(get_engine()) as session:
        rows = session.exec(select(Claim).where(Claim.paper_id == paper_id)).all()
        assert len(rows) == 3
        assert {r.source for r in rows} == {"ai"}
        assert {r.kind for r in rows} == {"main"}


def test_claim_extraction_degrades_on_bad_output(client):
    _seed_chat_provider()
    _enable_extraction(True)
    with Session(get_engine()) as session:
        paper = _paper_with_summary(session, "降级论文", {"results": "x"})
        paper_id = paper.id

    for bad in ("not json at all", "```json\n{'claims': [1, 2]}\n```", ""):
        with patch("app.providers.client.ProviderClient.complete", return_value=_completion(bad)):
            with Session(get_engine()) as session:
                paper = session.get(Paper, paper_id)
                assert extract_claims(session, paper) == 0

    with patch(
        "app.providers.client.ProviderClient.complete",
        side_effect=RuntimeError("boom"),
    ):
        with Session(get_engine()) as session:
            paper = session.get(Paper, paper_id)
            assert extract_claims(session, paper) == 0


def test_manual_claim_crud_api(client):
    with Session(get_engine()) as session:
        paper = _paper(session, "手动论断论文")
        other = _paper(session, "别的论文")
        pid, other_id = paper.id, other.id

    # 空列表
    assert client.get(f"/api/papers/{pid}/claims").json() == []

    resp = client.post(f"/api/papers/{pid}/claims", json={"text": "该模型在小样本下依然稳健"})
    assert resp.status_code == 201
    claim = resp.json()
    assert claim["source"] == "user"
    assert claim["kind"] == "main"

    # 论断归属校验：别的论文的摘录不能挂
    from app.models import PaperExcerpt

    with Session(get_engine()) as session:
        excerpt = PaperExcerpt(paper_id=other_id, quote="不属于本文")
        session.add(excerpt)
        session.commit()
        session.refresh(excerpt)
        excerpt_id = excerpt.id
    resp = client.post(
        f"/api/papers/{pid}/claims",
        json={"text": "x", "kind": "supporting", "excerpt_id": excerpt_id},
    )
    assert resp.status_code == 422

    # 合法 kind + 归属摘录
    with Session(get_engine()) as session:
        own = PaperExcerpt(paper_id=pid, quote="本文摘录")
        session.add(own)
        session.commit()
        session.refresh(own)
        own_id = own.id
    resp = client.post(
        f"/api/papers/{pid}/claims",
        json={"text": "摘录支撑的论断", "kind": "supporting", "excerpt_id": own_id},
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "supporting"

    listed = client.get(f"/api/papers/{pid}/claims").json()
    assert len(listed) == 2

    # 软删除后列表不再显示，行仍在
    claim_id = listed[0]["id"]
    assert client.delete(f"/api/claims/{claim_id}").status_code == 204
    listed = client.get(f"/api/papers/{pid}/claims").json()
    assert all(item["id"] != claim_id for item in listed)
    with Session(get_engine()) as session:
        row = session.get(Claim, claim_id)
        assert row is not None and row.is_deleted is True

    assert client.post(f"/api/papers/{pid}/claims", json={"text": "  "}).status_code == 422
    assert client.post(f"/api/papers/{pid}/claims", json={"text": "x", "kind": "bad"}).status_code == 422
    assert client.get("/api/papers/999999/claims").status_code == 404
    assert client.delete("/api/claims/999999").status_code == 404


# ---------------------------------------------------------------------------
# P12.3 论断关系（矛盾检测扩展）
# ---------------------------------------------------------------------------


def test_analyze_claim_relations_creates_relation_and_suggestion(client):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        a = _paper_with_concept(session, "新论文", "对比学习", ["新论文论断：对比学习优于监督学习"])
        b = _paper_with_concept(session, "旧论文", "对比学习", ["旧论文论断：监督学习更稳定"])
        a_id, b_id = a.id, b.id

    claim_a = client.get(f"/api/papers/{a_id}/claims").json()[0]
    claim_b = client.get(f"/api/papers/{b_id}/claims").json()[0]
    llm = json.dumps(
        {
            "relations": [
                {
                    "claim_a_id": claim_a["id"],
                    "claim_b_id": claim_b["id"],
                    "type": "contradicts",
                    "reason": "两者对训练范式的结论相反",
                }
            ]
        },
        ensure_ascii=False,
    )
    with patch("app.providers.client.ProviderClient.complete", return_value=_completion(llm)):
        with Session(get_engine()) as session:
            paper = session.get(Paper, a_id)
            assert analyze_claim_relations(session, paper) == 1

    with Session(get_engine()) as session:
        rel = session.exec(select(ClaimRelation)).one()
        lo, hi = sorted((claim_a["id"], claim_b["id"]))
        assert (rel.claim_a_id, rel.claim_b_id) == (lo, hi)  # 规范序存储
        assert rel.type == "contradicts"
        assert rel.source == "ai"
        assert "训练范式" in (rel.note or "")

        suggestion = session.exec(select(Suggestion).where(Suggestion.kind == "claim_relation")).one()
        assert suggestion.dedup_key == f"claim_rel:{lo}:{hi}:contradicts"
        detail = json.loads(suggestion.detail_json)
        assert detail["type"] == "contradicts"
        assert {detail["from_paper_id"], detail["to_paper_id"]} == {min(a_id, b_id), max(a_id, b_id)}
        # 建议带双论文，供「转为 Idea」复用
        assert suggestion.paper_id is not None and suggestion.related_paper_id is not None

    # 幂等：重跑不再新增关系与建议
    with patch("app.providers.client.ProviderClient.complete", return_value=_completion(llm)):
        with Session(get_engine()) as session:
            paper = session.get(Paper, a_id)
            assert analyze_claim_relations(session, paper) == 0
    with Session(get_engine()) as session:
        assert len(session.exec(select(ClaimRelation)).all()) == 1
        assert len(session.exec(select(Suggestion).where(Suggestion.kind == "claim_relation")).all()) == 1


def test_analyze_claim_relations_skips_without_claims_or_llm(client):
    with Session(get_engine()) as session:
        a = _paper_with_concept(session, "无论断论文", "联邦学习", [])
        b = _paper_with_concept(session, "邻接论文", "联邦学习", ["邻接论断"])
        a_id = a.id

    with patch("app.providers.client.ProviderClient.complete") as mock:
        with Session(get_engine()) as session:
            paper = session.get(Paper, a_id)
            assert analyze_claim_relations(session, paper) == 0
        mock.assert_not_called()  # 无论断就不该烧 LLM

    _seed_chat_provider()
    with Session(get_engine()) as session:
        # 新论文有论断、近邻没有 → 也不调用
        c = _paper_with_concept(session, "孤立论文", "知识蒸馏", ["孤立论断"])
        c_id = c.id
    with patch("app.providers.client.ProviderClient.complete") as mock:
        with Session(get_engine()) as session:
            paper = session.get(Paper, c_id)
            assert analyze_claim_relations(session, paper) == 0
        mock.assert_not_called()

    with Session(get_engine()) as session:
        d = _paper_with_concept(session, "有论断论文", "提示工程", ["提示论断一", "提示论断二"])
        e = _paper_with_concept(session, "近邻论文", "提示工程", ["近邻论断"])
        d_id = d.id
    with patch(
        "app.providers.client.ProviderClient.complete",
        side_effect=RuntimeError("llm down"),
    ):
        with Session(get_engine()) as session:
            paper = session.get(Paper, d_id)
            assert analyze_claim_relations(session, paper) == 0


# ---------------------------------------------------------------------------
# P12.4 论断图 API（前端 tab 在前端构建中验收）
# ---------------------------------------------------------------------------


def test_claims_graph_api_shape_and_filters(client):
    with Session(get_engine()) as session:
        a = _paper_with_concept(session, "图论文甲", "图神经网络", ["甲的论断"])
        b = _paper_with_concept(session, "图论文乙", "图神经网络", ["乙的论断", "乙的第二个论断"])
        dead = _paper_with_concept(session, "被删论文", "图神经网络", ["被删论断"])
        a_id, b_id = a.id, b.id
        claims_a = client.get(f"/api/papers/{a_id}/claims").json()
        claims_b = client.get(f"/api/papers/{b_id}/claims").json()
        session.add(
            ClaimRelation(
                claim_a_id=min(claims_a[0]["id"], claims_b[0]["id"]),
                claim_b_id=max(claims_a[0]["id"], claims_b[0]["id"]),
                type="contradicts",
                source="ai",
                note="矛盾理由",
            )
        )
        # 被软删的论断不出现在图里
        session.add(Claim(paper_id=b_id, text="已删论断", kind="main", source="ai", is_deleted=True))
        # 软删论文的论断不出现在图里
        dead.is_deleted = True
        session.add(dead)
        session.commit()

    data = client.get("/api/graph/claims").json()
    labels = [n["label"] for n in data["nodes"]]
    assert any("甲的论断" in label for label in labels)
    assert all("已删论断" not in label for label in labels)
    assert all("被删论断" not in label for label in labels)
    node = next(n for n in data["nodes"] if "甲的论断" in n["label"])
    assert node["paper_id"] == a_id
    assert node["paper_title"] == "图论文甲"
    assert node["kind"] == "main"

    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["edge_type"] == "contradicts"
    assert edge["note"] == "矛盾理由"

    # 类型过滤：supports 过滤后无矛盾边
    filtered = client.get("/api/graph/claims?types=supports").json()
    assert filtered["nodes"] and filtered["edges"] == []
    assert client.get("/api/graph/claims?types=bogus").status_code == 400
    assert client.get("/api/graph/claims?types=").status_code == 400


# ---------------------------------------------------------------------------
# P12 验收演示（代码级）：入库两篇结论相左的论文 → 论断图出现 contradicts 边
# → 建议中心出现矛盾提示 → 从该建议直接创建 Idea（origin=suggestion）。
# ---------------------------------------------------------------------------


def test_acceptance_contradiction_edge_to_idea_end_to_end(client):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        a = _paper_with_concept(
            session,
            "对比学习新论文",
            "对比学习",
            ["对比学习在小样本下优于监督学习"],
        )
        b = _paper_with_concept(
            session,
            "监督学习旧论文",
            "对比学习",
            ["监督学习在小样本场景显著优于对比学习"],
        )
        a_id, b_id = a.id, b.id

    claim_a = client.get(f"/api/papers/{a_id}/claims").json()[0]
    claim_b = client.get(f"/api/papers/{b_id}/claims").json()[0]
    llm = json.dumps(
        {
            "relations": [
                {
                    "claim_a_id": claim_a["id"],
                    "claim_b_id": claim_b["id"],
                    "type": "contradicts",
                    "reason": "两篇论文对同一场景的最优范式结论相反",
                }
            ]
        },
        ensure_ascii=False,
    )
    with patch("app.providers.client.ProviderClient.complete", return_value=_completion(llm)):
        with Session(get_engine()) as session:
            paper = session.get(Paper, a_id)
            assert analyze_claim_relations(session, paper) == 1

    # 论断图出现 contradicts 边
    graph = client.get("/api/graph/claims").json()
    assert any(edge["edge_type"] == "contradicts" for edge in graph["edges"])

    # 建议中心出现矛盾提示（带双论文，前端「转为 Idea」直接可用）
    suggestions = client.get("/api/suggestions").json()
    claim_suggestion = next(s for s in suggestions if s["kind"] == "claim_relation")
    assert claim_suggestion["paper"] and claim_suggestion["related_paper"]

    # 从建议直接创建 Idea（origin=suggestion，双论文按前端映射角色）
    detail = json.loads(json.dumps(claim_suggestion["detail"]))
    from_id = claim_suggestion["paper"]["id"]
    to_id = claim_suggestion["related_paper"]["id"]
    resp = client.post(
        "/api/ideas",
        json={
            "title": claim_suggestion["title"],
            "content": f"来源：AI 论断关系建议。\n\n{detail['reason']}",
            "origin": "suggestion",
            "papers": [
                {"paper_id": from_id, "role": "basis"},
                {"paper_id": to_id, "role": "contrast"},
            ],
        },
    )
    assert resp.status_code in (200, 201)
    idea = resp.json()
    assert idea["origin"] == "suggestion"
    assert {link["paper_id"] for link in idea["papers"]} == {from_id, to_id}
