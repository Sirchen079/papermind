"""Card 24: the thinking level is user-selected everywhere; unset means high."""
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.models import Provider
from app.providers.client import (
    DEFAULT_REASONING_EFFORT,
    ProviderClient,
    _generation_timeout,
    _review_generation_timeout,
)


def glm_provider():
    return Provider(id=1, name='test', type='openai_chat',
                    base_url='https://open.bigmodel.cn/api/coding/paas/v4')


def plain_provider():
    return Provider(id=2, name='plain', type='openai_chat', base_url='https://api.openai.com/v1')


def make_client(monkeypatch, sent, *, configured=None, supports_reasoning=True):
    def completion(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='answer', tool_calls=[]))], usage=None)

    monkeypatch.setattr('litellm.completion', completion)
    monkeypatch.setattr('litellm.supports_reasoning', lambda **k: supports_reasoning)
    client = ProviderClient(None, None)
    monkeypatch.setattr(client, '_record_usage', lambda *a, **k: None)
    monkeypatch.setattr(client, '_configured_effort', lambda p, m: configured)
    return client


def test_default_effort_is_high():
    assert DEFAULT_REASONING_EFFORT == 'high'


def test_unset_model_defaults_to_high_on_official_glm(monkeypatch):
    sent = []
    client = make_client(monkeypatch, sent)
    client.complete(glm_provider(), 'glm-5.3', [{'role': 'user', 'content': 'q'}], 'research')
    assert sent[0]['extra_body']['reasoning_effort'] == 'high'


def test_user_selected_effort_always_wins(monkeypatch):
    sent = []
    make_client(monkeypatch, sent, configured='max').complete(
        glm_provider(), 'glm-5.3', [{'role': 'user', 'content': 'q'}], 'research')
    assert sent[0]['extra_body']['reasoning_effort'] == 'max'
    make_client(monkeypatch, sent, configured='low').complete(
        glm_provider(), 'glm-5.3', [{'role': 'user', 'content': 'q'}], 'research')
    assert sent[-1]['extra_body']['reasoning_effort'] == 'low'


def test_reasoning_unsupported_model_without_setting_sends_no_reasoning(monkeypatch):
    sent = []
    client = make_client(monkeypatch, sent, supports_reasoning=False)
    client.complete(plain_provider(), 'gpt-4o', [{'role': 'user', 'content': 'q'}], 'chat')
    assert 'reasoning_effort' not in sent[0] and 'reasoning' not in sent[0]


def test_stream_chat_route_sends_thinking_params_and_scaled_timeout(monkeypatch):
    sent = []

    def completion(**kwargs):
        sent.append(kwargs)
        return iter([SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content='hi'))], usage=None)])

    monkeypatch.setattr('litellm.completion', completion)
    monkeypatch.setattr('litellm.supports_reasoning', lambda **k: True)
    client = ProviderClient(None, None)
    monkeypatch.setattr(client, '_record_usage', lambda *a, **k: None)
    monkeypatch.setattr(client, '_configured_effort', lambda p, m: 'max')
    provider = glm_provider()
    events = list(client.stream_complete(provider, 'glm-5.3',
                                         [{'role': 'user', 'content': 'q'}], 'chat'))
    assert events[-1].done and events[-1].content == 'hi'
    assert sent[0]['extra_body']['reasoning_effort'] == 'max'
    assert sent[0]['timeout'] == _generation_timeout(provider.base_url, 'max')


def test_timeouts_follow_effective_effort(monkeypatch):
    # _generation_timeout itself: max reads 1200s, high stays 600s.
    assert _generation_timeout('https://api.example.com/v1', 'max').read == 1200
    assert _generation_timeout('https://api.example.com/v1', 'high').read == 600
    # library_review: xhigh/max 1800s, others 900s.
    assert _review_generation_timeout('https://api.example.com/v1', 'max').read == 1800
    assert _review_generation_timeout('https://api.example.com/v1', 'high').read == 900

    provider = glm_provider()
    sent = []
    make_client(monkeypatch, sent).complete(
        provider, 'glm-5.3', [{'role': 'user', 'content': 'q'}], 'research')
    assert sent[0]['timeout'] == _generation_timeout(provider.base_url, 'high')  # default high
    sent = []
    make_client(monkeypatch, sent, configured='low').complete(
        provider, 'glm-5.3', [{'role': 'user', 'content': 'q'}], 'research')
    assert sent[0]['timeout'] == 90  # user low keeps the original bound
    sent = []
    make_client(monkeypatch, sent, configured='low').complete(
        provider, 'glm-5.3', [{'role': 'user', 'content': 'q'}], 'retrieval_query')
    assert sent[0]['timeout'] == 45
    sent = []
    make_client(monkeypatch, sent, configured='max').complete(
        provider, 'glm-5.3', [{'role': 'user', 'content': 'q'}], 'library_review',
        max_tokens=100)
    assert sent[0]['timeout'] == httpx.Timeout(1800, connect=10, write=60, pool=60)
    sent = []
    make_client(monkeypatch, sent).complete(  # unset -> high
        provider, 'glm-5.3', [{'role': 'user', 'content': 'q'}], 'library_review',
        max_tokens=100)
    assert sent[0]['timeout'] == httpx.Timeout(900, connect=10, write=60, pool=60)


def test_no_hardcoded_effort_or_or_low_left_in_app_code():
    """卡 24 源码守卫：档位只能来自用户设置或 DEFAULT_REASONING_EFFORT。"""
    direct = re.compile(r"reasoning_effort\s*=\s*['\"](low|medium|high|xhigh|max)['\"]")
    or_low = re.compile(r"or\s+['\"]low['\"]")
    # 白名单：与思考等级无关的代码写在这里并注明原因（目前没有）。
    whitelist: dict[str, str] = {}
    hits = []
    for path in Path('app').rglob('*.py'):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if (direct.search(line) or or_low.search(line)) and f'{path}' not in whitelist:
                hits.append(f'{path.as_posix()}:{number}:{line.strip()}')
    assert hits == []
