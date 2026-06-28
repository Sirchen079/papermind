import pytest

from app.providers.routing import route_completion


def test_openai_chat():
    r = route_completion("openai_chat", "gpt-4o", None)
    assert r.litellm_model == "openai/gpt-4o"
    assert r.api_base is None
    assert r.call == "completion"


def test_openai_chat_honors_base_url():
    # openai_chat must NOT silently drop base_url (same class of bug as the old
    # anthropic hardcode): a user who fills a custom endpoint must reach it,
    # else their vendor key hits api.openai.com and 401s confusingly.
    r = route_completion("openai_chat", "gpt-4o", "https://my-openai-proxy.example.com/v1")
    assert r.litellm_model == "openai/gpt-4o"
    assert r.api_base == "https://my-openai-proxy.example.com/v1"
    assert r.call == "completion"


def test_openai_compat_uses_base_url():
    r = route_completion("openai_compat", "deepseek-chat", "https://api.deepseek.com/v1")
    assert r.litellm_model == "openai/deepseek-chat"
    assert r.api_base == "https://api.deepseek.com/v1"
    assert r.call == "completion"


def test_openai_compat_requires_base_url():
    with pytest.raises(ValueError):
        route_completion("openai_compat", "deepseek-chat", None)


def test_anthropic_without_base_url():
    r = route_completion("anthropic", "claude-opus-4-8", None)
    assert r.litellm_model == "anthropic/claude-opus-4-8"
    assert r.api_base is None  # LiteLLM falls back to api.anthropic.com
    assert r.call == "completion"


def test_anthropic_honors_base_url():
    # A Claude-format relay/gateway must be used — never hardcoded to
    # api.anthropic.com. LiteLLM appends /v1/messages itself, so api_base is
    # the host root.
    r = route_completion("anthropic", "claude-opus-4-8", "https://relay.example.com")
    assert r.litellm_model == "anthropic/claude-opus-4-8"
    assert r.api_base == "https://relay.example.com"
    assert r.call == "completion"


def test_anthropic_base_url_strips_trailing_v1():
    # Users paste either form; a trailing /v1 must be dropped so LiteLLM does
    # not build /v1/v1/messages.
    r = route_completion("anthropic", "claude-opus-4-8", "https://relay.example.com/v1/")
    assert r.api_base == "https://relay.example.com"


def test_openai_responses():
    r = route_completion("openai_responses", "gpt-4o", None)
    assert r.call == "responses"


def test_openai_responses_honors_base_url():
    r = route_completion("openai_responses", "gpt-4o", "https://my-proxy.example.com/v1")
    assert r.call == "responses"
    assert r.api_base == "https://my-proxy.example.com/v1"


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        route_completion("weird", "x", None)
