from unittest.mock import patch

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Model, Provider
from app.providers.client import CompletionResult


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
