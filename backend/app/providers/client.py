from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import httpx
import litellm
from sqlmodel import Session

from app.models import Provider, TokenUsage
from app.providers.routing import route_completion
from app.security.crypto import Crypto


@dataclass
class CompletionResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ModelInfo:
    model_id: str
    display_name: str | None = None
    context_window: int | None = None


def _utc_date() -> date:
    return datetime.now(timezone.utc).date()


class ProviderClient:
    """Unified LLM access over LiteLLM, with per-call token recording.

    P0a provides a non-streaming ``complete()`` and ``list_models()``. The
    agent layer (P2) adds a ``tools`` parameter for custom + provider-native
    tool pass-through; this signature is designed to accept it then.
    """

    def __init__(self, session_factory: Callable[[], Session], crypto: Crypto) -> None:
        self._session_factory = session_factory
        self._crypto = crypto

    def _api_key(self, provider: Provider) -> str | None:
        if not provider.api_key_encrypted:
            return None
        return self._crypto.decrypt(provider.api_key_encrypted)

    def complete(
        self,
        provider: Provider,
        model_id: str,
        messages: list[dict[str, Any]],
        request_kind: str,
        ref_id: str | None = None,
    ) -> CompletionResult:
        route = route_completion(provider.type, model_id, provider.base_url)
        kwargs: dict[str, Any] = {
            "model": route.litellm_model,
            "messages": messages,
            "api_key": self._api_key(provider),
        }
        if route.api_base:
            kwargs["api_base"] = route.api_base

        if route.call == "responses":
            # OpenAI Responses API. Detail/validation lands in P2; this branch
            # is best-effort for P0a's abstraction.
            resp = litellm.responses(**kwargs)
            content = getattr(resp, "output_text", None) or ""
            usage = getattr(resp, "usage", None)
        else:
            resp = litellm.completion(**kwargs)
            content = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)

        prompt_t = getattr(usage, "prompt_tokens", 0) or 0
        completion_t = getattr(usage, "completion_tokens", 0) or 0
        total_t = getattr(usage, "total_tokens", None) or (prompt_t + completion_t)

        self._record_usage(provider, model_id, request_kind, ref_id, prompt_t, completion_t, total_t)
        return CompletionResult(content, prompt_t, completion_t, total_t)

    def _record_usage(
        self,
        provider: Provider,
        model_id: str,
        request_kind: str,
        ref_id: str | None,
        prompt_t: int,
        completion_t: int,
        total_t: int,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                TokenUsage(
                    provider_id=provider.id,
                    model=model_id,
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                    request_kind=request_kind,
                    ref_id=ref_id,
                    day=_utc_date(),
                )
            )
            session.commit()

    def list_models(self, provider: Provider) -> list[ModelInfo]:
        url, headers = self._models_endpoint(provider)
        data = httpx.get(url, headers=headers, timeout=30.0).json()
        raw = data.get("data", data) if isinstance(data, dict) else data
        out: list[ModelInfo] = []
        for item in raw or []:
            mid = item.get("id") or item.get("model") or item.get("name")
            if not mid:
                continue
            out.append(ModelInfo(model_id=mid, display_name=item.get("id")))
        return out

    def _models_endpoint(self, provider: Provider) -> tuple[str, dict[str, str]]:
        key = self._api_key(provider)
        if provider.type in {"openai_chat", "openai_responses", "openai_compat"}:
            base = (provider.base_url or "https://api.openai.com/v1").rstrip("/")
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            return f"{base}/models", headers
        if provider.type == "anthropic":
            return "https://api.anthropic.com/v1/models", {
                "x-api-key": key or "",
                "anthropic-version": "2023-06-01",
            }
        raise ValueError(f"no models endpoint for type {provider.type}")
