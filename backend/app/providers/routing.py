from dataclasses import dataclass
from enum import StrEnum


class ProviderType(StrEnum):
    openai_chat = "openai_chat"
    openai_responses = "openai_responses"
    anthropic = "anthropic"
    openai_compat = "openai_compat"


@dataclass(frozen=True)
class CompletionRoute:
    litellm_model: str
    api_base: str | None
    call: str  # "completion" | "responses"


def anthropic_api_base(base_url: str | None) -> str | None:
    """Normalize an Anthropic provider base_url for LiteLLM.

    LiteLLM *itself* appends ``/v1/messages`` (and ``/v1/models``) to whatever
    ``api_base`` we pass, so the api_base must be the host root — NOT a path
    already ending in ``/v1``. We strip a trailing slash and a trailing
    ``/v1`` so users can paste either ``https://relay.com`` or
    ``https://relay.com/v1`` and both work.

    Returns ``None`` when no base_url is configured; LiteLLM then falls back to
    its default (``https://api.anthropic.com``), which is correct for direct
    access. See https://docs.litellm.ai/docs/providers/anthropic (custom API base).
    """
    if not base_url:
        return None
    b = base_url.rstrip("/")
    if b.endswith("/v1"):
        b = b[: -len("/v1")]
    return b or None


def route_completion(provider_type: str, model_id: str, base_url: str | None) -> CompletionRoute:
    """Map a provider type + model id to LiteLLM call arguments.

    - openai_chat:      LiteLLM ``openai/<model>`` via completion(). base_url is
                        honored when set (custom OpenAI-format endpoint); None
                        falls back to the official api.openai.com.
    - openai_compat:    same shape, but base_url is REQUIRED (DeepSeek, 智谱,
                        Moonshot, SiliconFlow, Ollama, …). OpenAI-compat servers
                        serve ``/v1/chat/completions``, so base_url keeps its
                        ``/v1`` (LiteLLM appends only ``/chat/completions``).
    - anthropic:        LiteLLM ``anthropic/<model>`` via completion(). Honors a
                        custom base_url (relay/网关/Bedrock-format proxy); LiteLLM
                        appends ``/v1/messages`` itself, so we pass the host root.
    - openai_responses: OpenAI Responses API via litellm.responses(). base_url is
                        honored when set.
    """
    if provider_type == "openai_chat":
        return CompletionRoute(f"openai/{model_id}", base_url, "completion")
    if provider_type == "openai_compat":
        if not base_url:
            raise ValueError("openai_compat provider requires base_url")
        return CompletionRoute(f"openai/{model_id}", base_url, "completion")
    if provider_type == "anthropic":
        return CompletionRoute(f"anthropic/{model_id}", anthropic_api_base(base_url), "completion")
    if provider_type == "openai_responses":
        return CompletionRoute(f"openai/{model_id}", base_url, "responses")
    raise ValueError(f"unknown provider type: {provider_type}")
