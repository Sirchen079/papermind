from unittest.mock import MagicMock

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
