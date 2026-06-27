from dataclasses import dataclass


@dataclass(frozen=True)
class CompletionRoute:
    litellm_model: str
    api_base: str | None
    call: str  # "completion" | "responses"


def route_completion(provider_type: str, model_id: str, base_url: str | None) -> CompletionRoute:
    """Map a provider type + model id to LiteLLM call arguments.

    - openai_chat:     LiteLLM ``openai/<model>`` via completion()
    - openai_compat:   same, but with the provider's base_url (DeepSeek, 智谱,
                       Moonshot, SiliconFlow, Ollama, ...)
    - anthropic:       LiteLLM ``anthropic/<model>`` via completion()
    - openai_responses: OpenAI Responses API via litellm.responses()
    """
    if provider_type == "openai_chat":
        return CompletionRoute(f"openai/{model_id}", None, "completion")
    if provider_type == "openai_compat":
        if not base_url:
            raise ValueError("openai_compat provider requires base_url")
        return CompletionRoute(f"openai/{model_id}", base_url, "completion")
    if provider_type == "anthropic":
        return CompletionRoute(f"anthropic/{model_id}", None, "completion")
    if provider_type == "openai_responses":
        return CompletionRoute(f"openai/{model_id}", None, "responses")
    raise ValueError(f"unknown provider type: {provider_type}")
