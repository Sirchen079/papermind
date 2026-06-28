from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Model, Paper, PaperChunk, Provider
from app.providers.client import ToolTurn


def test_chat_message_returns_and_persists_sources(client, monkeypatch):
    with Session(get_engine()) as s:
        p = Provider(name="oai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", role_default="chat"))
        paper = Paper(source="pdf", title="The Causality Paper")
        s.add(paper)
        s.commit()
        s.refresh(paper)
        pid = paper.id

    # Fake retrieval: one chunk on the paper above.
    def fake_retrieve(session, query, k=5):  # noqa: ANN001
        return [
            (PaperChunk(paper_id=pid, ordinal=0, text="Causality is about cause and effect."), 0.9)
        ]

    monkeypatch.setattr("app.rag.index.retrieve", fake_retrieve)

    def fake_complete(self, provider, model_id, messages, request_kind, tools=None, ref_id=None):  # noqa: ANN001
        return ToolTurn(content="ok", tool_calls=[], prompt_tokens=1, completion_tokens=1, total_tokens=2)

    monkeypatch.setattr("app.providers.client.ProviderClient.complete_with_tools", fake_complete)

    cid = client.post("/api/chat/conversations").json()["id"]
    res = client.post(
        f"/api/chat/conversations/{cid}/messages", json={"content": "explain causality"}
    )
    body = res.json()
    assert body["sources"], "expected RAG sources on the response"
    assert body["sources"][0]["paper_id"] == pid
    assert "Causality" in body["sources"][0]["title"]
    assert "cause and effect" in body["sources"][0]["snippet"]

    # Sources persist on the message and come back via the conversation endpoint.
    conv = client.get(f"/api/chat/conversations/{cid}").json()
    assistant = [m for m in conv["messages"] if m["role"] == "assistant"]
    assert assistant and assistant[-1]["sources"][0]["paper_id"] == pid


def test_chat_sources_empty_without_retrieval(client, monkeypatch):
    with Session(get_engine()) as s:
        p = Provider(name="oai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", role_default="chat"))
        s.commit()

    monkeypatch.setattr("app.rag.index.retrieve", lambda *a, **k: [])

    def fake_complete(self, provider, model_id, messages, request_kind, tools=None, ref_id=None):  # noqa: ANN001
        return ToolTurn(content="ok", tool_calls=[], prompt_tokens=1, completion_tokens=1, total_tokens=2)

    monkeypatch.setattr("app.providers.client.ProviderClient.complete_with_tools", fake_complete)

    cid = client.post("/api/chat/conversations").json()["id"]
    res = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "hi"})
    assert res.json()["sources"] == []
