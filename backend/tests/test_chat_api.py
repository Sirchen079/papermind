import json
from unittest.mock import patch

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Model, Provider, Skill
from app.providers.client import CompletionResult, StreamEvent


def _seed_chat_provider():
    with Session(get_engine()) as s:
        p = Provider(name="oai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", role_default="chat"))
        s.commit()


def test_chat_requires_provider(client):
    cid = client.post("/api/chat/conversations").json()["id"]
    res = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "hi"})
    assert res.status_code == 400


def test_chat_roundtrip(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    fake = CompletionResult(content="Hello from the assistant", prompt_tokens=5, completion_tokens=5, total_tokens=10)
    with patch("app.providers.client.ProviderClient.complete", return_value=fake):
        res = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "summarize my library"})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "assistant"
    assert body["content"] == "Hello from the assistant"

    convo = client.get(f"/api/chat/conversations/{cid}").json()
    roles = [m["role"] for m in convo["messages"]]
    assert roles == ["user", "assistant"]


def test_stream_message_requires_provider(client):
    cid = client.post("/api/chat/conversations").json()["id"]
    res = client.post(f"/api/chat/conversations/{cid}/messages/stream", json={"content": "hi"})
    assert res.status_code == 400


def test_stream_message_emits_sse_and_persists(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    events = iter([
        StreamEvent("Hello ", "", 0, 0, 0, False),
        StreamEvent("world", "", 0, 0, 0, False),
        StreamEvent(None, "Hello world", 10, 5, 15, True),
    ])
    with patch("app.providers.client.ProviderClient.stream_complete", return_value=events):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages/stream",
            json={"content": "summarize"},
        )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    body = res.text
    assert 'event: delta\ndata: {"content": "Hello "' in body
    assert 'event: delta\ndata: {"content": "world"}' in body
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
        yield  # noqa: E704 — make it a generator

    with patch("app.providers.client.ProviderClient.stream_complete", side_effect=boom):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages/stream",
            json={"content": "hi"},
        )
    assert res.status_code == 200  # error is an SSE frame, not an HTTP error
    assert "event: error" in res.text
    assert "upstream down" in res.text
    # no assistant message persisted
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

    def fake_stream(provider, model_id, messages, request_kind, ref_id=None):  # noqa: ANN001
        captured["messages"] = messages
        return iter([
            StreamEvent("ok", "", 0, 0, 0, False),
            StreamEvent(None, "ok", 1, 1, 2, True),
        ])

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.stream_complete", side_effect=fake_stream):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages/stream",
            json={"content": "please check the math"},
        )
    assert res.status_code == 200
    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "Use mathematical rigor." in sys_msg


def test_first_message_auto_titles_conversation(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    fake = CompletionResult(content="ok", prompt_tokens=1, completion_tokens=1, total_tokens=2)
    with patch("app.providers.client.ProviderClient.complete", return_value=fake):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "  Compare   transformer   architectures  "},
        )
    assert res.status_code == 200
    assert res.json()["title"] == "Compare transformer architectures"
    # sidebar list reflects the derived title
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
    fake = CompletionResult(content="ok", prompt_tokens=1, completion_tokens=1, total_tokens=2)
    with patch("app.providers.client.ProviderClient.complete", return_value=fake):
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "hi"})
    assert len(client.get(f"/api/chat/conversations/{cid}").json()["messages"]) == 2
    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 204
    assert client.get(f"/api/chat/conversations/{cid}").status_code == 404
    assert all(c["id"] != cid for c in client.get("/api/chat/conversations").json())
