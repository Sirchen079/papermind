from unittest.mock import MagicMock

import pytest
import httpx
import respx
from cryptography.fernet import Fernet
from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Provider, TokenUsage
from app.providers.client import CompletionResult, ModelInfo, ProviderClient
from app.security.crypto import Crypto


def _fake_litellm_completion(**kwargs):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="hello world"))]
    resp.usage = MagicMock(prompt_tokens=12, completion_tokens=8, total_tokens=20)
    return resp


def test_complete_records_usage(tmp_path, monkeypatch):
    eng = make_engine(tmp_path / "c.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(Fernet.generate_key())

    monkeypatch.setattr("app.providers.client.litellm.completion", _fake_litellm_completion)

    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    # Persist the provider so the tokenusage foreign key is satisfied.
    with Session(eng) as s:
        provider = Provider(
            name="oai",
            type="openai_chat",
            base_url=None,
            api_key_encrypted=crypto.encrypt("sk-x"),
        )
        s.add(provider)
        s.commit()
        s.refresh(provider)

    result = client.complete(
        provider, "gpt-4o", [{"role": "user", "content": "hi"}], request_kind="chat"
    )
    assert isinstance(result, CompletionResult)
    assert result.content == "hello world"
    assert result.total_tokens == 20

    with Session(eng) as s:
        rows = s.exec(select(TokenUsage)).all()
    assert len(rows) == 1
    assert rows[0].total_tokens == 20
    assert rows[0].request_kind == "chat"
    assert rows[0].model == "gpt-4o"
    assert rows[0].provider_id == provider.id


@respx.mock
def test_list_models_openai_compat(tmp_path):
    eng = make_engine(tmp_path / "c.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(Fernet.generate_key())
    respx.get("https://api.deepseek.com/v1/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}
        )
    )
    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    provider = Provider(
        id=1,
        name="ds",
        type="openai_compat",
        base_url="https://api.deepseek.com/v1",
        api_key_encrypted=crypto.encrypt("sk-x"),
    )
    models = client.list_models(provider)
    assert {m.model_id for m in models} == {"deepseek-chat", "deepseek-reasoner"}
    assert all(isinstance(m, ModelInfo) for m in models)


@respx.mock
def test_list_models_raises_on_error_status(tmp_path):
    """A 401/error body must raise, not crash with AttributeError iterating keys."""
    import pytest

    eng = make_engine(tmp_path / "err.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(Fernet.generate_key())
    respx.get("https://api.deepseek.com/v1/models").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    provider = Provider(
        id=1,
        name="ds",
        type="openai_compat",
        base_url="https://api.deepseek.com/v1",
        api_key_encrypted=crypto.encrypt("sk-x"),
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.list_models(provider)


@respx.mock
def test_list_models_anthropic_uses_base_url(tmp_path):
    """A Claude-format provider with a base_url (relay/网关) must hit THAT host,
    not api.anthropic.com. Also confirms the trailing /v1 is stripped so the
    request is /v1/models, not /v1/v1/models. The response is Anthropic's real
    List Models shape: {data:[{id,...}], has_more}.
    """
    eng = make_engine(tmp_path / "anth.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(Fernet.generate_key())
    # Mock the RELAY only — if base_url were ignored this 404s (all mocked,
    # unmatched -> no response) and the test fails.
    respx.get("https://claude-relay.example.com/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "claude-sonnet-4-5", "type": "model", "display_name": "Claude Sonnet 4.5"},
                    {"id": "claude-opus-4-8", "type": "model"},
                ],
                "has_more": False,
                "first_id": "claude-sonnet-4-5",
                "last_id": "claude-opus-4-8",
            },
        )
    )
    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    provider = Provider(
        id=1,
        name="relay",
        type="anthropic",
        base_url="https://claude-relay.example.com/v1",
        api_key_encrypted=crypto.encrypt("sk-ant-x"),
    )
    models = client.list_models(provider)
    assert {m.model_id for m in models} == {"claude-sonnet-4-5", "claude-opus-4-8"}


# --- "两种 API 格式，任意厂商 + 任意模型" 契约测试 -------------------------------
# 与本文件其它用例不同：这里不 mock litellm.completion，而是用 respx 拦在 HTTP 边界，
# 跑真实的 LiteLLM 协议转换，从而证明一个不在任何模型注册表里的厂商自定义模型名，
# 能按对应格式正确发到用户填的 base_url。这是「导入符合这两种格式的 API、想用啥模型
# 用啥模型」这一核心诉求的回归守护。

def _provider(tmp_path, ptype, base_url):
    eng = make_engine(tmp_path / f"{ptype}.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(Fernet.generate_key())
    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    provider = Provider(
        name=f"{ptype}-vendor", type=ptype,
        base_url=base_url, api_key_encrypted=crypto.encrypt("sk-vendor-key"),
    )
    # Persist so _record_usage's TokenUsage FK (provider_id) is satisfied.
    with Session(eng) as s:
        s.add(provider)
        s.commit()
        s.refresh(provider)
    return client, provider


@respx.mock
def test_anthropic_format_accepts_arbitrary_vendor_and_model(tmp_path):
    """Anthropic 格式：自定义 base_url + 厂商自定义模型名 -> /v1/messages，
    body.model 原样透传，x-api-key + anthropic-version 契约齐全。"""
    base = "http://fake-anthropic-vendor.example.com/v1"
    client, provider = _provider(tmp_path, "anthropic", base)
    custom_model = "acme-corp-ninja-70b"  # 不在 litellm 任何注册表里

    respx.post("http://fake-anthropic-vendor.example.com/v1/messages").mock(
        return_value=httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": custom_model,
            "content": [{"type": "text", "text": "任意厂商回复"}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "stop_reason": "end_turn",
        })
    )
    result = client.complete(
        provider, custom_model, [{"role": "user", "content": "ping"}], request_kind="chat"
    )

    req = respx.calls[0].request
    assert str(req.url) == "http://fake-anthropic-vendor.example.com/v1/messages"  # /v1 未重复
    headers = {k.lower(): v for k, v in req.headers.items()}
    assert headers["x-api-key"] == "sk-vendor-key"
    assert "anthropic-version" in headers
    import json
    body = json.loads(req.content.decode())
    assert body["model"] == custom_model  # 厂商自定义模型名原样透传，未被注册表拒绝
    assert "任意厂商回复" in result.content


@respx.mock
def test_openai_format_accepts_arbitrary_vendor_and_model(tmp_path):
    """OpenAI 格式（openai_compat）：自定义 base_url + 厂商自定义模型名
    -> /v1/chat/completions，body.model 原样透传，Authorization: Bearer 契约齐全。"""
    base = "http://fake-openai-vendor.example.com/v1"
    client, provider = _provider(tmp_path, "openai_compat", base)
    custom_model = "acme-corp-ninja-70b"

    respx.post("http://fake-openai-vendor.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "任意厂商回复"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })
    )
    result = client.complete(
        provider, custom_model, [{"role": "user", "content": "ping"}], request_kind="chat"
    )

    req = respx.calls[0].request
    assert str(req.url) == "http://fake-openai-vendor.example.com/v1/chat/completions"
    headers = {k.lower(): v for k, v in req.headers.items()}
    assert headers["authorization"] == "Bearer sk-vendor-key"
    import json
    body = json.loads(req.content.decode())
    assert body["model"] == custom_model
    assert "任意厂商回复" in result.content
