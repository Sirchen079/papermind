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
        json={"name": "s1", "type": "instruction", "body": "do X", "keywords": ["x"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "s1"
    assert body["keywords"] == ["x"]
    assert len(client.get("/api/skills").json()) == 1
    sid = body["id"]
    assert client.delete(f"/api/skills/{sid}").status_code == 204
    assert client.get("/api/skills").json() == []


def test_chat_injects_active_skill(client):
    with Session(get_engine()) as s:
        p = Provider(name="oai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", role_default="chat"))
        s.commit()
    client.post(
        "/api/skills",
        json={"name": "reviewer", "type": "instruction", "body": "Be critical.", "enabled": True},
    )

    captured: dict = {}

    def fake_complete(provider, model_id, messages, request_kind, ref_id=None):  # noqa: ANN001
        captured["messages"] = messages
        return CompletionResult(content="ok", prompt_tokens=1, completion_tokens=1, total_tokens=2)

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.complete", side_effect=fake_complete):
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "hi"})

    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "Be critical." in sys_msg
