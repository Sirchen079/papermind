import json
from unittest.mock import patch

from sqlmodel import Session, SQLModel, select

from app.db.engine import get_engine, make_engine
from app.models import Model, Provider, Skill
from app.providers.client import CompletionResult
from app.skills.loader import load_skills_from_dir, parse_skill_file

SAMPLE = """---
name: deep-review
description: Deep review a paper
type: instruction
trigger: manual
keywords: review, critique
model_role: deep
---
Review the paper for:
1. Problem
2. Method
3. Limitations
"""


def test_parse_skill_file(tmp_path):
    p = tmp_path / "deep-review.md"
    p.write_text(SAMPLE, encoding="utf-8")
    data = parse_skill_file(p)
    assert data["name"] == "deep-review"
    assert data["type"] == "instruction"
    assert data["trigger"] == "manual"
    assert "review" in data["keywords_json"]
    assert data["model_role"] == "deep"
    assert "Review the paper" in data["body"]


def test_parse_skill_no_frontmatter(tmp_path):
    p = tmp_path / "plain.md"
    p.write_text("Just a body, no frontmatter.")
    data = parse_skill_file(p)
    assert data["name"] == "plain"
    assert data["body"] == "Just a body, no frontmatter."


def test_load_skills_upsert(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "a.md").write_text("---\nname: a\ntype: instruction\n---\nbody A")
    eng = make_engine(tmp_path / "s.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        assert load_skills_from_dir(s, d) == 1
        assert load_skills_from_dir(s, d) == 1  # second scan upserts, no duplicate
        assert len(s.exec(select(Skill)).all()) == 1


def test_skills_api_crud(client):
    res = client.post(
        "/api/skills",
        json={"name": "s1", "type": "instruction", "body": "do X", "keywords": [" x ", "", "y"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "s1"
    assert body["keywords"] == ["x", "y"]
    assert len(client.get("/api/skills").json()) == 1
    sid = body["id"]
    assert client.delete(f"/api/skills/{sid}").status_code == 204
    assert client.get("/api/skills").json() == []


def test_skills_api_tolerates_malformed_keyword_json(client):
    with Session(get_engine()) as s:
        s.add(Skill(name="bad", type="instruction", keywords_json="not-json", body="x"))
        s.commit()
    res = client.get("/api/skills")
    assert res.status_code == 200
    assert res.json()[0]["keywords"] == []


def test_skills_api_lists_in_creation_order(client):
    client.post("/api/skills", json={"name": "first", "type": "instruction", "body": "1"})
    client.post("/api/skills", json={"name": "second", "type": "instruction", "body": "2"})
    assert [s["name"] for s in client.get("/api/skills").json()] == ["first", "second"]


def test_skills_api_rejects_unknown_type_or_trigger(client):
    assert client.post("/api/skills", json={"name": "bad-type", "type": "unknown"}).status_code == 422
    assert client.post("/api/skills", json={"name": "bad-trigger", "trigger": "unknown"}).status_code == 422


def test_select_for_chat_respects_skill_triggers(tmp_path):
    from app.skills.activation import select_for_chat

    eng = make_engine(tmp_path / "activation.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Skill(name="auto", type="instruction", trigger="auto", body="Always active."))
        s.add(
            Skill(
                name="keyword",
                type="instruction",
                trigger="keyword",
                keywords_json=json.dumps(["review", "critique"]),
                body="Triggered by keyword.",
            )
        )
        s.add(Skill(name="manual", type="instruction", trigger="manual", body="Manual only."))
        s.add(Skill(name="pipeline", type="instruction", trigger="pipeline", body="Pipeline only."))
        s.add(Skill(name="disabled", type="instruction", trigger="auto", body="Disabled.", enabled=False))
        s.add(Skill(name="template", type="template", trigger="auto", body="Templates are not injected."))
        s.commit()

        active = select_for_chat(s, "please review this paper")
        bodies = [sk.body for sk in active]
        assert bodies == ["Always active.", "Triggered by keyword."]

        active = select_for_chat(s, "hello")
        bodies = [sk.body for sk in active]
        assert bodies == ["Always active."]


def test_select_for_chat_ignores_malformed_keyword_json(tmp_path):
    from app.skills.activation import select_for_chat

    eng = make_engine(tmp_path / "bad_keywords.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(
            Skill(
                name="bad-keywords",
                type="instruction",
                trigger="keyword",
                keywords_json="not-json",
                body="Should not crash.",
            )
        )
        s.commit()
        assert select_for_chat(s, "not-json") == []


def test_select_for_chat_keyword_boundary_matching(tmp_path):
    from app.skills.activation import select_for_chat

    eng = make_engine(tmp_path / "keyword_boundary.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(
            Skill(
                name="ai-keyword",
                type="instruction",
                trigger="keyword",
                keywords_json=json.dumps(["ai"]),
                body="AI keyword matched.",
            )
        )
        s.add(
            Skill(
                name="zh-keyword",
                type="instruction",
                trigger="keyword",
                keywords_json=json.dumps(["论文"]),
                body="Chinese keyword matched.",
            )
        )
        s.commit()
        assert select_for_chat(s, "chain of thought") == []
        assert [sk.name for sk in select_for_chat(s, "AI review")] == ["ai-keyword"]
        assert [sk.name for sk in select_for_chat(s, "帮我分析论文")] == ["zh-keyword"]


def test_chat_injects_auto_and_matching_keyword_skills_only(client):
    with Session(get_engine()) as s:
        p = Provider(name="oai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", role_default="chat"))
        s.commit()
    client.post(
        "/api/skills",
        json={
            "name": "auto-reviewer",
            "type": "instruction",
            "trigger": "auto",
            "body": "Always be critical.",
            "enabled": True,
        },
    )
    client.post(
        "/api/skills",
        json={
            "name": "keyword-reviewer",
            "type": "instruction",
            "trigger": "keyword",
            "keywords": ["review"],
            "body": "Use review checklist.",
            "enabled": True,
        },
    )
    client.post(
        "/api/skills",
        json={
            "name": "manual-reviewer",
            "type": "instruction",
            "trigger": "manual",
            "keywords": ["review"],
            "body": "Manual skill should not auto inject.",
            "enabled": True,
        },
    )

    captured: dict = {}

    def fake_complete(provider, model_id, messages, request_kind, ref_id=None):  # noqa: ANN001
        captured["messages"] = messages
        return CompletionResult(content="ok", prompt_tokens=1, completion_tokens=1, total_tokens=2)

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.complete", side_effect=fake_complete):
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "please review this"})

    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "Always be critical." in sys_msg
    assert "Use review checklist." in sys_msg
    assert "Manual skill should not auto inject." not in sys_msg
