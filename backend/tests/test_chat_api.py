import json
import copy
from unittest.mock import patch
import pytest

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import (
    Concept,
    Model,
    Paper,
    PaperConcept,
    PaperExcerpt,
    PaperNote,
    Provider,
    ReviewMatrixEntry,
    Skill,
    Summary,
)
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


@pytest.mark.parametrize("suffix", ["messages", "messages/stream"])
def test_conversation_history_and_selection_are_isolated(client, suffix):
    _seed_chat_provider()
    old = client.post("/api/chat/conversations").json()["id"]
    new = client.post("/api/chat/conversations").json()["id"]
    captured = []

    def complete(provider, model_id, messages, request_kind, **kwargs):
        captured.append(copy.deepcopy(messages))
        return _turn("OLD_ANSWER" if len(captured) == 1 else "NEW_ANSWER")

    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=complete):
        assert client.post(f"/api/chat/conversations/{old}/{suffix}", json={
            "content": "OLD_PRIVATE_QUESTION", "selected_text": "OLD_SELECTED_PASSAGE"
        }).status_code == 200
        assert client.post(f"/api/chat/conversations/{new}/{suffix}", json={"content": "NEW_QUESTION"}).status_code == 200
        assert client.post(f"/api/chat/conversations/{old}/{suffix}", json={"content": "OLD_FOLLOWUP"}).status_code == 200
    new_prompt = json.dumps(captured[1])
    assert "OLD_PRIVATE_QUESTION" not in new_prompt
    assert "OLD_SELECTED_PASSAGE" not in new_prompt
    assert "OLD_ANSWER" not in new_prompt
    assert [m["content"].split('[本轮用户问题]\n')[-1] for m in captured[1] if m["role"] != "system"] == ["NEW_QUESTION"]
    assert [m["content"].split('[本轮用户问题]\n')[-1] for m in captured[2] if m["role"] != "system"] == [
        "OLD_PRIVATE_QUESTION", "OLD_ANSWER", "OLD_FOLLOWUP"
    ]
    assert captured[2][:2] == captured[0][:2]  # original material remains in its own historical turn
    assert "OLD_SELECTED_PASSAGE" not in captured[2][-1]['content']
    assert [m["content"] for m in client.get(f"/api/chat/conversations/{new}").json()["messages"]] == ["NEW_QUESTION", "NEW_ANSWER"]


def test_deleted_conversation_late_stream_cannot_write_to_new_conversation(client):
    _seed_chat_provider()
    old = client.post("/api/chat/conversations").json()["id"]
    created = []

    def complete(*args, **kwargs):
        assert client.delete(f"/api/chat/conversations/{old}").status_code == 204
        created.append(client.post("/api/chat/conversations").json()["id"])
        return _turn("LATE_OLD_REPLY")

    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=complete):
        response = client.post(f"/api/chat/conversations/{old}/messages/stream", json={"content": "old request"})
    assert created[0] > old
    assert "event: error" in response.text
    assert client.get(f"/api/chat/conversations/{created[0]}").json()["messages"] == []
    assert client.post(f"/api/chat/conversations/{old}/messages", json={"content": "stale tab"}).status_code == 404


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
    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "user")
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


# ---- T5：论文上下文问答 ----


def _seed_scoped_paper(*, soft_deleted: bool = False) -> int:
    """Seed one paper with summary/notes/excerpts/matrix; return its id."""
    with Session(get_engine()) as s:
        paper = Paper(
            source="manual",
            title="Scoped Attention 论文",
            authors_json='["Alice","Bob"]',
            year=2024,
            venue="NeurIPS",
            doi="10.1000/scoped",
            arxiv_id="2401.00001",
            abstract="An abstract about scoped attention.",
        )
        if soft_deleted:
            paper.is_deleted = True
        s.add(paper)
        s.commit()
        s.refresh(paper)
        pid = paper.id
        s.add(
            Summary(
                paper_id=pid,
                content_json=json.dumps(
                    {"problem": "如何压缩注意力", "method": "稀疏注意力"}, ensure_ascii=False
                ),
            )
        )
        s.add(PaperNote(paper_id=pid, kind="critique", content="实验只测了小模型。", tags_json="[]"))
        s.add(PaperExcerpt(paper_id=pid, quote="Scoped attention reduces cost.", page=3, note="关键论据"))
        s.add(ReviewMatrixEntry(paper_id=pid, problem="注意力开销大", method="稀疏化"))
        s.commit()
    return pid


def _capture_system_message(fake_cwt):  # noqa: ANN001
    messages = fake_cwt.call_args.kwargs.get("messages") or fake_cwt.call_args.args[2]
    return next(m["content"] for m in messages if m["role"] == "system")


def test_sync_chat_with_paper_context_carries_user_materials(client):
    _seed_chat_provider()
    pid = _seed_scoped_paper()
    captured: dict = {}

    def fake_cwt(provider, model_id, messages, request_kind, tools=None, ref_id=None):  # noqa: ANN001
        captured["messages"] = messages
        return _turn("基于论文的回答")

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=fake_cwt):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "这篇论文的方法可靠吗", "paper_id": pid, "selected_text": "scoped attention cuts cost by half"},
        )
    assert res.status_code == 200
    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "user")
    for expected in (
        "Scoped Attention 论文",
        "Alice",
        "NeurIPS",
        "如何压缩注意力",
        "实验只测了小模型",
        "Scoped attention reduces cost.",
        "注意力开销大",
        "scoped attention cuts cost by half",
    ):
        assert expected in sys_msg, f"missing {expected!r} in paper context"


def test_chat_without_paper_id_keeps_legacy_prompt(client):
    _seed_chat_provider()
    captured: dict = {}

    def fake_cwt(provider, model_id, messages, request_kind, tools=None, ref_id=None):  # noqa: ANN001
        captured["messages"] = messages
        return _turn("ok")

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=fake_cwt):
        res = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "hi"})
    assert res.status_code == 200
    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "论文上下文" not in sys_msg
    assert "当前选中文本" not in sys_msg


def test_chat_paper_context_rejects_missing_or_deleted_paper(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]

    missing = client.post(
        f"/api/chat/conversations/{cid}/messages", json={"content": "hi", "paper_id": 99999}
    )
    assert missing.status_code == 404

    deleted_id = _seed_scoped_paper(soft_deleted=True)
    deleted = client.post(
        f"/api/chat/conversations/{cid}/messages", json={"content": "hi", "paper_id": deleted_id}
    )
    assert deleted.status_code == 404

    # 校验失败时不应持久化用户消息。
    assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []


def test_chat_paper_context_truncates_long_sections(client):
    _seed_chat_provider()
    with Session(get_engine()) as s:
        paper = Paper(source="manual", title="Long Paper", authors_json="[]")
        s.add(paper)
        s.commit()
        s.refresh(paper)
        pid = paper.id
        s.add(PaperNote(paper_id=pid, kind="note", content="长" * 5000, tags_json="[]"))
        s.add(Summary(paper_id=pid, content_json=json.dumps({"problem": "问" * 5000}, ensure_ascii=False)))
        s.commit()

    captured: dict = {}

    def fake_cwt(provider, model_id, messages, request_kind, tools=None, ref_id=None):  # noqa: ANN001
        captured["messages"] = messages
        return _turn("ok")

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=fake_cwt):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "hi", "paper_id": pid, "selected_text": "x" * 6000},
        )
    assert res.status_code == 422  # selected_text 超长被请求校验拒绝

    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=fake_cwt):
        res = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "hi", "paper_id": pid, "selected_text": "x" * 3000},
        )
    assert res.status_code == 200
    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "user")
    # 每节截断后系统提示总长度受控（远小于原始 5000+5000+3000 字符）。
    assert len(sys_msg) < 12000
    # 5000 字的连续 run 被截断到小节上限内，不再完整出现。
    assert "问" * 2500 not in sys_msg
    assert "长" * 2500 not in sys_msg


def test_selected_text_requires_length_cap(client):
    _seed_chat_provider()
    cid = client.post("/api/chat/conversations").json()["id"]
    res = client.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "hi", "selected_text": "x" * 4001},
    )
    assert res.status_code == 422


def test_system_prompt_directs_note_questions_to_research_notes_tool(client):
    """T7：系统提示告知 Agent 用 search_research_notes 回答用户自身沉淀的问题。"""
    _seed_chat_provider()
    captured: dict = {}

    def fake_cwt(provider, model_id, messages, request_kind, tools=None, ref_id=None):  # noqa: ANN001
        captured["messages"] = messages
        captured["tools"] = tools
        return _turn("ok")

    cid = client.post("/api/chat/conversations").json()["id"]
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=fake_cwt):
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "我批注过什么？"})
    sys_msg = next(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "search_research_notes" in sys_msg
    assert "笔记、摘录、批注、判断或审阅矩阵" in sys_msg
    tool_names = {t["function"]["name"] for t in captured["tools"] or []}
    assert "search_research_notes" in tool_names
