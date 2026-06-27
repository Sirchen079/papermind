import pytest

from app.providers.routing import route_completion


def test_openai_chat():
    r = route_completion("openai_chat", "gpt-4o", None)
    assert r.litellm_model == "openai/gpt-4o"
    assert r.api_base is None
    assert r.call == "completion"


def test_openai_compat_uses_base_url():
    r = route_completion("openai_compat", "deepseek-chat", "https://api.deepseek.com/v1")
    assert r.litellm_model == "openai/deepseek-chat"
    assert r.api_base == "https://api.deepseek.com/v1"
    assert r.call == "completion"


def test_openai_compat_requires_base_url():
    with pytest.raises(ValueError):
        route_completion("openai_compat", "deepseek-chat", None)


def test_anthropic():
    r = route_completion("anthropic", "claude-opus-4-8", None)
    assert r.litellm_model == "anthropic/claude-opus-4-8"
    assert r.call == "completion"


def test_openai_responses():
    r = route_completion("openai_responses", "gpt-4o", None)
    assert r.call == "responses"


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        route_completion("weird", "x", None)
