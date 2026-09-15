from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Conversation, Message, Model, Paper, PaperChunk, Provider
from app.providers.client import ToolCall, ToolTurn
import json
import pytest
pytestmark=pytest.mark.usefixtures('accept_evidence_review')


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


def test_conversation_tolerates_malformed_persisted_sources(client):
    with Session(get_engine()) as s:
        conv = Conversation(title="Malformed sources")
        s.add(conv)
        s.commit()
        s.refresh(conv)
        s.add(
            Message(
                conversation_id=conv.id,
                role="assistant",
                content="old answer",
                sources_json="not-json",
            )
        )
        s.commit()
        cid = conv.id

    res = client.get(f"/api/chat/conversations/{cid}")

    assert res.status_code == 200
    body = res.json()
    assert body["messages"][0]["content"] == "old answer"
    assert body["messages"][0]["sources"] == []


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_tool_discovered_source_survives_full_text_truncation_and_reload(client, monkeypatch, suffix):
    with Session(get_engine()) as session:
        provider = Provider(name='Synthetic', type='openai_chat')
        session.add(provider); session.commit()
        session.add(Model(provider_id=provider.id, model_id='synthetic', role_default='chat'))
        paper = Paper(source='manual', title='Evidence outside initial retrieval', full_text='Retrieved evidence. ' * 200)
        session.add(paper); session.commit()
        pid = paper.id
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    turns = iter([
        ToolTurn('', [ToolCall('read', 'get_paper_full_text', {'paper_id': pid})], 1, 1, 2),
        ToolTurn('A bounded conclusion.', [], 1, 1, 2),
    ])
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', lambda *a, **k: next(turns))
    cid = client.post('/api/chat/conversations').json()['id']
    response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Read the evidence'})
    assert response.status_code == 200
    if suffix.endswith('stream'):
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        returned = frames[-1]['sources']
    else:
        returned = response.json()['sources']
    assert len(returned) == 1
    assert returned[0]['paper_id'] == pid
    assert returned[0]['source_type'] == 'full_text'
    assert 'Retrieved evidence' in returned[0]['snippet']
    restored = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]['sources']
    assert restored == returned
