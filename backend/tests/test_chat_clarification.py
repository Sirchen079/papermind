import pytest
pytestmark=pytest.mark.usefixtures("accept_evidence_review")

"""ask_user is a durable human boundary, not a model-generated tool result."""
import copy
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Model, Provider
from app.providers.client import ToolCall, ToolTurn


def turn(content="", calls=()):
    return ToolTurn(content=content, tool_calls=list(calls), prompt_tokens=3, completion_tokens=2, total_tokens=5)


def ask(arguments=None):
    return ToolCall(id="ask_1", name="ask_user", arguments=arguments or {
        "reason": "范围会影响比较方式。",
        "questions": [
            {"question": "这次用于什么？", "options": ["组会汇报", "论文相关工作"]},
            {"question": "希望比较哪些方面？"},
        ],
    })


@pytest.fixture
def chat(client):
    with Session(get_engine()) as session:
        provider = Provider(name="qa", type="openai_chat")
        session.add(provider); session.commit(); session.refresh(provider)
        session.add(Model(provider_id=provider.id, model_id="qa-model", role_default="chat"))
        session.commit()
    return client, client.post("/api/chat/conversations").json()["id"]


def messages(client, cid):
    return client.get(f"/api/chat/conversations/{cid}").json()["messages"]


def create_question(client, cid, suffix="messages"):
    with patch("app.providers.client.ProviderClient.complete_with_tools", return_value=turn(calls=[ask()])) as model:
        response = client.post(f"/api/chat/conversations/{cid}/{suffix}", json={
            "content": "帮我比较这些论文", "selected_text": "ORIGINAL_MATERIAL",
        })
    assert response.status_code == 200
    assert model.call_count == 1  # no automatic calls while waiting for a person
    rows = messages(client, cid)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert all(row["delivery_status"] == "complete" for row in rows)
    assert rows[-1]["clarification"]["status"] == "pending"
    assert "agent_state_json" not in json.dumps(rows)
    if suffix.endswith("stream"):
        assert "event: ask_user" in response.text
        assert "event: done" not in response.text
        assert "ORIGINAL_MATERIAL" not in response.text
    else:
        assert response.json()["clarification"]["message_id"] == rows[-1]["id"]
    return rows[-1]["id"]


@pytest.mark.parametrize("suffix", ["messages", "messages/stream"])
def test_pause_survives_restart_and_answer_resumes_original_tool_context(chat, suffix):
    client, cid = chat
    first_turns = [turn(calls=[ToolCall(id="lookup", name="list_concepts", arguments={})]), turn(calls=[ask()])]
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=first_turns) as model:
        r = client.post(f"/api/chat/conversations/{cid}/{suffix}", json={"content": "比较论文", "selected_text": "ORIGINAL_MATERIAL"})
    assert r.status_code == 200 and model.call_count == 2
    qid = messages(client, cid)[-1]["id"]
    from app.main import create_app
    restarted = TestClient(create_app())
    assert messages(restarted, cid)[-1]["clarification"]["status"] == "pending"
    captured = []
    def complete(provider, model_id, prompt, kind, **kwargs):
        captured.append(copy.deepcopy(prompt))
        return turn("按组会用途比较方法与实验。")
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=complete):
        result = restarted.post(f"/api/chat/conversations/{cid}/{suffix}", json={
            "clarification_response": {"message_id": qid, "answers": {"q1": "组会汇报", "q2": "方法与实验"}},
            "selected_text": "WRONG_NEW_MATERIAL",
        })
    assert result.status_code == 200
    prompt = captured[0]
    assert "ORIGINAL_MATERIAL" in json.dumps(prompt)
    assert "WRONG_NEW_MATERIAL" not in json.dumps(prompt)
    assert any(row.get("tool_call_id") == "lookup" for row in prompt)
    assert prompt[-1]["role"] == "tool" and prompt[-1]["tool_call_id"] == "ask_1"
    assert json.loads(prompt[-1]["content"])["user_response"]["answers"]["q2"] == "方法与实验"
    rows = messages(restarted, cid)
    assert [row["role"] for row in rows] == ["user", "assistant", "user", "assistant"]
    assert rows[1]["clarification"]["status"] == "answered"
    assert rows[-1]["content"] == "按组会用途比较方法与实验。"


@pytest.mark.parametrize("mode", ["skip", "free_text", "composer"])
def test_skip_and_free_text_continue_without_invented_preferences(chat, mode):
    client, cid = chat
    qid = create_question(client, cid, "messages/stream")
    body = {"content": "我想改成整理相关工作"} if mode == "composer" else {
        "clarification_response": {"message_id": qid, **({"skipped": True} if mode == "skip" else {"free_text": "偏重实验，请简短一些"})},
    }
    with patch("app.providers.client.ProviderClient.complete_with_tools", return_value=turn("继续处理")) as model:
        assert client.post(f"/api/chat/conversations/{cid}/messages", json=body).status_code == 200
    result = json.loads(model.call_args.args[2][-1]["content"])["user_response"]
    assert result["answers"] == {}
    assert result["skipped"] == (mode == "skip")
    assert messages(client, cid)[1]["clarification"]["status"] == ("skipped" if mode == "skip" else "answered")


def test_mixed_tool_batch_has_no_side_effects_before_user_answers(chat):
    client, cid = chat
    mutation = ToolCall(id="tag", name="tag_paper", arguments={"paper_id": 1, "tag_name": "未确认的分类"})
    from app.agent.tools import get_tool
    with patch.object(get_tool("tag_paper"), "run") as mutate, patch(
        "app.providers.client.ProviderClient.complete_with_tools", return_value=turn(calls=[mutation, ask()])
    ) as model:
        assert client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "帮我分类"}).status_code == 200
    mutate.assert_not_called()
    assert model.call_count == 1
    with patch("app.providers.client.ProviderClient.complete_with_tools", return_value=turn("继续")) as model:
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "按研究主题分类"})
    prompt = model.call_args.args[2]
    assert [row["tool_call_id"] for row in prompt if row["role"] == "tool"] == ["tag", "ask_1"]
    assert "未执行" in next(row["content"] for row in prompt if row.get("tool_call_id") == "tag")


def test_duplicate_cross_conversation_and_incomplete_answers_rejected_without_writes(chat):
    client, cid = chat
    qid = create_question(client, cid)
    other = client.post("/api/chat/conversations").json()["id"]
    valid = {"clarification_response": {"message_id": qid, "answers": {"q1": "组会汇报", "q2": "实验"}}}
    assert client.post(f"/api/chat/conversations/{other}/messages", json=valid).status_code == 409
    assert client.post(f"/api/chat/conversations/{cid}/messages", json={
        "clarification_response": {"message_id": qid, "answers": {"q1": "组会汇报"}},
    }).status_code == 422
    assert len(messages(client, cid)) == 2 and messages(client, other) == []
    with patch("app.providers.client.ProviderClient.complete_with_tools", return_value=turn("完成")) as model:
        assert client.post(f"/api/chat/conversations/{cid}/messages", json=valid).status_code == 200
        assert client.post(f"/api/chat/conversations/{cid}/messages", json=valid).status_code == 409
    assert model.call_count == 1
    assert len(messages(client, cid)) == 4


@pytest.mark.parametrize("suffix", ["messages", "messages/stream"])
def test_failed_continuation_retries_same_answer_with_same_context(chat, suffix):
    client, cid = chat
    qid = create_question(client, cid)
    body = {"clarification_response": {"message_id": qid, "free_text": "组会汇报，比较实验"}}
    captured = []
    def fail(provider, model, prompt, kind, **kwargs):
        captured.append(copy.deepcopy(prompt)); raise RuntimeError("503 simulated")
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=fail):
        r = client.post(f"/api/chat/conversations/{cid}/{suffix}", json=body)
    assert r.status_code in (200, 500)
    rows = messages(client, cid)
    assert len(rows) == 3 and rows[-1]["delivery_status"] == "failed" and rows[-1]["retryable"]
    with patch("app.providers.client.ProviderClient.complete_with_tools", return_value=turn("恢复后的结果")) as model:
        r = client.post(f"/api/chat/conversations/{cid}/{suffix}", json={"content": rows[-1]["content"], "retry_message_id": rows[-1]["id"]})
    assert r.status_code == 200
    assert model.call_args.args[2] == captured[0]
    rows = messages(client, cid)
    assert [row["role"] for row in rows] == ["user", "assistant", "user", "assistant"]
    assert all(row["delivery_status"] == "complete" for row in rows)


def test_invalid_model_question_is_recoverable_not_a_waiting_card(chat):
    client, cid = chat
    turns = [turn(calls=[ask({"questions": [{"question": "   "}]})]), turn("请补充研究用途。")]
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=turns) as model:
        r = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "比较一下"})
    assert r.status_code == 200 and model.call_count == 2
    assert messages(client, cid)[-1]["clarification"] is None
