"""Background review calls back off on transient provider errors (W1).

A real 106-paper map run stopped at card 103 because three concurrent
requests hit one provider-side InternalServerError. Only ``library_review``
retries; interactive kinds keep their single bounded attempt.
"""
from types import SimpleNamespace

import httpx
import litellm
import pytest
from cryptography.fernet import Fernet
from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Provider, TokenUsage
from app.providers import client as client_mod
from app.providers.client import ProviderClient
from app.reviews.structured import ModelUnavailable, StructuredAsker
from app.security.crypto import Crypto


def _provider(tmp_path, ptype='openai_compat'):
    eng = make_engine(tmp_path / f'{ptype}.sqlite')
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(Fernet.generate_key())
    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    provider = Provider(name=f'{ptype}-vendor', type=ptype, base_url='https://test.invalid/v1',
                        api_key_encrypted=crypto.encrypt('sk-vendor-key'))
    with Session(eng) as s:
        s.add(provider)
        s.commit()
        s.refresh(provider)
    return client, provider, eng


def _ok(ptype):
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5)
    if ptype == 'openai_responses':
        return SimpleNamespace(output_text='draft', output=[], usage=usage)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='draft'), finish_reason='stop')],
                           usage=usage)


def _response(status, headers=None):
    return httpx.Response(status, headers=headers or {}, request=httpx.Request('POST', 'https://test.invalid/v1'))


def _err(cls, status=500, headers=None):
    if cls is litellm.Timeout:
        return cls(message='read timed out', model='writer', llm_provider='openai')
    if cls is litellm.APIConnectionError:
        return cls(message='connection reset', llm_provider='openai', model='writer')
    if cls is litellm.NotFoundError:
        return cls(message='no such model', model='writer', llm_provider='openai', response=_response(404))
    return cls(message='provider said no', llm_provider='openai', model='writer',
               response=_response(status, headers))


class Script:
    def __init__(self, ptype, items):
        self.ptype, self.items, self.calls = ptype, list(items), 0

    def __call__(self, **kwargs):
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return _ok(self.ptype)


@pytest.fixture
def sleeps(monkeypatch):
    seen = []
    monkeypatch.setattr(client_mod, '_retry_sleep', seen.append)
    return seen


def _install(monkeypatch, script):
    monkeypatch.setattr('app.providers.client.litellm.completion', script)
    monkeypatch.setattr('app.providers.client.litellm.responses', script)


@pytest.mark.parametrize('ptype', ['openai_compat', 'openai_responses'])
def test_review_call_recovers_after_transient_errors(tmp_path, monkeypatch, sleeps, ptype):
    client, provider, eng = _provider(tmp_path, ptype)
    script = Script(ptype, [_err(litellm.InternalServerError), _err(litellm.BadGatewayError, 502), 'ok'])
    _install(monkeypatch, script)

    result = client.complete(provider, 'writer', [{'role': 'user', 'content': 'x'}], request_kind='library_review')

    assert result.content == 'draft'
    assert script.calls == 3
    assert sleeps == [5, 20]
    with Session(eng) as s:
        assert len(s.exec(select(TokenUsage)).all()) == 1  # usage only for the successful call


def test_review_call_gives_up_after_bounded_retries(tmp_path, monkeypatch, sleeps):
    client, provider, _ = _provider(tmp_path)
    script = Script('openai_compat', [_err(litellm.ServiceUnavailableError, 503) for _ in range(4)])
    _install(monkeypatch, script)

    with pytest.raises(litellm.ServiceUnavailableError):
        client.complete(provider, 'writer', [{'role': 'user', 'content': 'x'}], request_kind='library_review')

    assert script.calls == 4
    assert sleeps == [5, 20, 60]


def test_connection_errors_and_rate_limits_are_retried(tmp_path, monkeypatch, sleeps):
    client, provider, _ = _provider(tmp_path)
    script = Script('openai_compat', [_err(litellm.APIConnectionError), _err(litellm.RateLimitError, 429), 'ok'])
    _install(monkeypatch, script)

    assert client.complete(provider, 'writer', [{'role': 'user', 'content': 'x'}],
                           request_kind='library_review').content == 'draft'
    assert script.calls == 3


@pytest.mark.parametrize('header,expected', [('90', 90), ('999', 120), ('2', 5), ('soon', 5)])
def test_rate_limit_honours_retry_after_within_cap(tmp_path, monkeypatch, sleeps, header, expected):
    client, provider, _ = _provider(tmp_path)
    script = Script('openai_compat', [_err(litellm.RateLimitError, 429, {'Retry-After': header}), 'ok'])
    _install(monkeypatch, script)

    client.complete(provider, 'writer', [{'role': 'user', 'content': 'x'}], request_kind='library_review')

    assert sleeps == [expected]


@pytest.mark.parametrize('cls', [litellm.AuthenticationError, litellm.Timeout, litellm.NotFoundError])
def test_non_transient_errors_are_not_retried(tmp_path, monkeypatch, sleeps, cls):
    client, provider, _ = _provider(tmp_path)
    script = Script('openai_compat', [_err(cls, 401), 'ok'])
    _install(monkeypatch, script)

    with pytest.raises(cls):
        client.complete(provider, 'writer', [{'role': 'user', 'content': 'x'}], request_kind='library_review')

    assert script.calls == 1
    assert sleeps == []


@pytest.mark.parametrize('kind', ['chat', 'research', 'rerank_llm', 'evidence_review'])
def test_interactive_kinds_keep_a_single_attempt(tmp_path, monkeypatch, sleeps, kind):
    client, provider, _ = _provider(tmp_path)
    script = Script('openai_compat', [_err(litellm.InternalServerError), 'ok'])
    _install(monkeypatch, script)

    with pytest.raises(litellm.InternalServerError):
        client.complete(provider, 'writer', [{'role': 'user', 'content': 'x'}], request_kind=kind)

    assert script.calls == 1
    assert sleeps == []


class Raising:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


def _asker(client):
    return StructuredAsker(client, SimpleNamespace(id=1, base_url=''), 'fake-model', ref_id='r1', window=32768)


@pytest.mark.parametrize('cls', [litellm.AuthenticationError, litellm.PermissionDeniedError, litellm.NotFoundError])
def test_rejected_credentials_stop_structured_tasks_at_once(cls):
    client = Raising(_err(cls, 403))
    with pytest.raises(ModelUnavailable) as caught:
        _asker(client).ask('s', 'u', 2000)
    assert client.calls == 1
    assert 'API key' in str(caught.value) and cls.__name__ in str(caught.value)


def test_other_errors_still_need_three_in_a_row():
    client = Raising(ValueError('bad output'))
    asker = _asker(client)
    for _ in range(2):
        with pytest.raises(ValueError):
            asker.ask('s', 'u', 2000)
    with pytest.raises(ModelUnavailable, match='连续 3 次'):
        asker.ask('s', 'u', 2000)
