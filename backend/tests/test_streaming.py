from unittest.mock import MagicMock

from cryptography.fernet import Fernet
from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Provider, TokenUsage
from app.providers.client import ProviderClient, StreamEvent
from app.security.crypto import Crypto


class _Usage:
    def __init__(self, p, c, t):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = t


class _Chunk:
    """Minimal stand-in for a LiteLLM streaming chunk."""

    def __init__(self, content=None, usage=None):
        delta = MagicMock()
        delta.content = content
        choice = MagicMock()
        choice.delta = delta
        self.choices = [choice]
        self.usage = usage


def _make_client(tmp_path):
    eng = make_engine(tmp_path / "s.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(Fernet.generate_key())
    with Session(eng) as s:
        s.add(Provider(id=1, name="oai", type="openai_chat",
                       api_key_encrypted=crypto.encrypt("sk-x")))
        s.commit()
    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    return client, eng


def _events(gen):
    return list(gen)


def test_stream_complete_yields_deltas_and_records_usage(tmp_path, monkeypatch):
    client, eng = _make_client(tmp_path)

    def fake_completion(**kwargs):
        assert kwargs["stream"] is True
        assert kwargs["stream_usage"] is True
        return iter([
            _Chunk("Hello "),
            _Chunk("world"),
            _Chunk(None, usage=_Usage(10, 5, 15)),
        ])

    monkeypatch.setattr("app.providers.client.litellm.completion", fake_completion)

    events = _events(client.stream_complete(
        Provider(id=1, name="oai", type="openai_chat"), "gpt-4o",
        [{"role": "user", "content": "hi"}], request_kind="chat"))

    deltas = [e for e in events if not e.done]
    done = [e for e in events if e.done][0]
    assert "".join(e.delta for e in deltas) == "Hello world"
    assert done.done is True
    assert done.content == "Hello world"
    assert done.total_tokens == 15

    with Session(eng) as s:
        rows = s.exec(select(TokenUsage)).all()
    assert len(rows) == 1
    assert rows[0].total_tokens == 15
    assert rows[0].request_kind == "chat"


def test_stream_complete_estimates_when_provider_omits_usage(tmp_path, monkeypatch):
    client, eng = _make_client(tmp_path)
    monkeypatch.setattr(
        "app.providers.client.litellm.completion",
        lambda **kw: iter([_Chunk("Hi"), _Chunk(" there")]),
    )
    events = _events(client.stream_complete(
        Provider(id=1, name="oai", type="openai_chat"), "gpt-4o",
        [{"role": "user", "content": "hi"}], request_kind="chat"))
    done = [e for e in events if e.done][0]
    assert done.content == "Hi there"
    assert done.total_tokens > 0  # estimated, never zero
    assert done.prompt_tokens > 0
    assert done.completion_tokens > 0
    with Session(eng) as s:
        assert len(s.exec(select(TokenUsage)).all()) == 1


def test_stream_complete_responses_route_degrades_to_one_shot(tmp_path, monkeypatch):
    client, eng = _make_client(tmp_path)

    fake_resp = MagicMock()
    fake_resp.output_text = "all at once"
    fake_resp.usage = _Usage(3, 3, 6)
    monkeypatch.setattr("app.providers.client.litellm.responses", lambda **kw: fake_resp)

    events = _events(client.stream_complete(
        Provider(id=1, name="oai", type="openai_responses"), "gpt-4o",
        [{"role": "user", "content": "hi"}], request_kind="chat"))
    assert len(events) == 1
    assert events[0].done is True
    assert events[0].content == "all at once"
    assert events[0].total_tokens == 6
