import json
from unittest.mock import patch

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Concept, Model, Paper, PaperConcept, Provider, Skill
from app.providers.client import ToolCall, ToolTurn


def _seed_chat_provider():
    with Session(get_engine()) as s:
        p = Provider(name="oai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", role_default="chat"))
        s.commit()


def _turn(content="ok", tool_calls=None):
    return ToolTurn(
        content=content,
        tool_calls=tool_calls or [],
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
    )


def test_chat_requires_provider(client):
    cid = client.post("/api/chat/conversations").json()["id"]
    res = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "hi"})
    assert res.status_code == 400


def test_chat_roundtrip(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    with patch(
        "app.providers.client.ProviderClient.complete_with_tools",
        return_value=_turn("Hello from the assistant"),
    ):
        res = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "summarize my library"})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "assistant"
    assert body["content"] == "Hello from the assistant"

    convo = client.get(f"/api/chat/conversations/{cid}").json()
    assert [m["role"] for m in convo["messages"]] == ["user", "assistant"]


def test_stream_message_requires_provider(client):
    cid = client.post("/api/chat/conversations").json()["id"]
    res = client.post(f"/api/chat/conversations/{cid}/messages/stream", json={"content": "hi"})
    assert res.status_code == 400


def test_stream_message_emits_sse_and_persists(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    with patch(
        "app.providers.client.ProviderClient.complete_with_tools",
        return_value=ToolTurn("Hello world", [], 10, 5, 15),
    ):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages/stream",
            json={"content": "summarize"},
        )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    body = res.text
    assert "event: delta" in body
    assert '"content": "Hello world"' in body
    assert "event: done" in body
    assert '"tokens": 15' in body

    convo = client.get(f"/api/chat/conversations/{cid}").json()
    msgs = convo["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[-1]["content"] == "Hello world"


def test_stream_message_emits_error_on_failure(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]

    def boom(*a, **k):
        raise RuntimeError("upstream down")

    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=boom):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages/stream",
            json={"content": "hi"},
        )
    assert res.status_code == 200  # error is an SSE frame, not an HTTP error
    assert "event: error" in res.text
    assert "upstream down" in res.text
    convo = client.get(f"/api/chat/conversations/{cid}").json()
    assert [m["role"] for m in convo["messages"]] == ["user"]


def test_stream_message_activates_keyword_skill_for_current_turn(client):
    _seed_chat_provider()
    with Session(get_engine()) as s:
        s.add(
            Skill(
                name="math-review",
                type="instruction",
                trigger="keyword",
                keywords_json=json.dumps(["math"]),
                body="Use mathematical rigor.",
            )
        )
        s.commit()

    captured: dict = {}

    def fake_cwt(provider, model_id, messages, request_kind, tools=None, ref_id=None):  # noqa: ANN001
        captured["messages"] = messages
        return _turn("ok")

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=fake_cwt):
        client.post(
            f"/api/chat/conversations/{cid}/messages/stream",
            json={"content": "please check the math"},
        )
    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "Use mathematical rigor." in sys_msg


def test_agent_calls_a_tool_then_answers(client):
    """The agent loop executes a returned tool call and feeds the result back."""
    _seed_chat_provider()
    with Session(get_engine()) as s:
        for name in ("transformers", "attention"):
            c = Concept(name=name, normalized_key=name)
            s.add(c)
            s.commit()
            s.refresh(c)
            p = Paper(source="bibtex", title=f"Paper on {name}")
            s.add(p)
            s.commit()
            s.refresh(p)
            s.add(PaperConcept(paper_id=p.id, concept_id=c.id, weight=1.0))
        s.commit()

    # First call: model wants list_concepts. Second call: final answer.
    turns = iter([
        _turn("", tool_calls=[ToolCall(id="call_1", name="list_concepts", arguments={})]),
        _turn("You have concepts like transformers and attention."),
    ])

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=lambda *a, **k: next(turns)):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages/stream",
            json={"content": "what concepts are in my library?"},
        )
    body = res.text
    assert "event: tool" in body
    assert '"name": "list_concepts"' in body
    assert "transformers" in body  # the tool result (JSON) is surfaced in the SSE
    assert "event: done" in body
    assert "transformers and attention" in body
    # assistant message persisted with the final answer
    convo = client.get(f"/api/chat/conversations/{cid}").json()
    assert convo["messages"][-1]["role"] == "assistant"
    assert "transformers and attention" in convo["messages"][-1]["content"]


def test_agent_degrades_when_provider_rejects_tools(client):
    """If tools are rejected, the loop retries plain and still answers."""
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    calls = {"n": 0}

    def flaky(provider, model_id, messages, request_kind, tools=None, ref_id=None):  # noqa: ANN001
        calls["n"] += 1
        if tools:
            raise RuntimeError("this provider does not support tools")
        return _turn("plain fallback answer")

    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=flaky):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages/stream",
            json={"content": "hi"},
        )
    assert "event: done" in res.text
    assert "plain fallback answer" in res.text
    assert calls["n"] == 2  # tried with tools, then degraded to plain


def test_first_message_auto_titles_conversation(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    with patch(
        "app.providers.client.ProviderClient.complete_with_tools",
        return_value=_turn("ok"),
    ):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "  Compare   transformer   architectures  "},
        )
    assert res.status_code == 200
    assert res.json()["title"] == "Compare transformer architectures"
    assert next(c for c in client.get("/api/chat/conversations").json() if c["id"] == cid)["title"] == "Compare transformer architectures"


def test_rename_conversation(client):
    cid = client.post("/api/chat/conversations").json()["id"]
    res = client.patch(f"/api/chat/conversations/{cid}", json={"title": "My topic"})
    assert res.status_code == 200
    assert res.json()["title"] == "My topic"


def test_rename_rejects_empty(client):
    cid = client.post("/api/chat/conversations").json()["id"]
    assert client.patch(f"/api/chat/conversations/{cid}", json={"title": "   "}).status_code == 400


def test_delete_conversation_clears_messages(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    with patch(
        "app.providers.client.ProviderClient.complete_with_tools",
        return_value=_turn("ok"),
    ):
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "hi"})
    assert len(client.get(f"/api/chat/conversations/{cid}").json()["messages"]) == 2
    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 204
    assert client.get(f"/api/chat/conversations/{cid}").status_code == 404
    assert all(c["id"] != cid for c in client.get("/api/chat/conversations").json())
