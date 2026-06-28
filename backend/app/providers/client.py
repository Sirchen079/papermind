from collections.abc import Callable, Iterator
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
class StreamEvent:
    """One chunk from a streaming completion.

    For content deltas ``delta`` is set and ``done`` is False; the final event
    has ``done=True`` with the full accumulated ``content`` and token totals.
    ``delta`` may be ``None`` if a chunk carries only usage metadata.
    """

    delta: str | None
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    done: bool


@dataclass
class ModelInfo:
    model_id: str
    display_name: str | None = None
    context_window: int | None = None


def _utc_date() -> date:
    return datetime.now(timezone.utc).date()


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for providers that omit usage."""
    return max(1, len(text) // 4)


def _responses_text(resp: Any) -> str:
    """Extract assistant text from a litellm Responses-API response.

    ``output_text`` is the convenience property on LiteLLM's
    ``ResponsesAPIResponse``, but it is not present in every version. Fall back
    to walking ``output[*].content[*]`` so we never silently return empty text
    (which would produce blank summaries / chat replies with no error).
    """
    text = getattr(resp, "output_text", None)
    if text:
        return text
    parts: list[str] = []
    for item in getattr(resp, "output", None) or []:
        content = getattr(item, "content", None)
        if isinstance(content, list):
            for block in content:
                t = getattr(block, "text", None)
                if not t and isinstance(block, dict):
                    t = block.get("text")
                if t:
                    parts.append(t)
        elif isinstance(content, str) and content:
            parts.append(content)
    return "".join(parts)


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
            content = _responses_text(resp)
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

    def stream_complete(
        self,
        provider: Provider,
        model_id: str,
        messages: list[dict[str, Any]],
        request_kind: str,
        ref_id: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Yield ``StreamEvent`` deltas, then a final ``done`` event.

        Token usage is read from the provider's final stream chunk when
        reported (``stream_usage=True``); otherwise it is estimated so the
        usage ledger still records a row. The Responses API streaming shape
        differs across LiteLLM versions, so that route degrades to a single
        one-shot chunk (still correct, just not incremental).
        """
        route = route_completion(provider.type, model_id, provider.base_url)
        kwargs: dict[str, Any] = {
            "model": route.litellm_model,
            "messages": messages,
            "api_key": self._api_key(provider),
        }
        if route.api_base:
            kwargs["api_base"] = route.api_base

        if route.call == "responses":
            result = self.complete(provider, model_id, messages, request_kind, ref_id)
            yield StreamEvent(result.content, result.content, result.prompt_tokens,
                              result.completion_tokens, result.total_tokens, done=True)
            return

        kwargs["stream"] = True
        # stream_usage is an OpenAI extension; conservative openai_compat
        # gateways (DeepSeek/智谱/Moonshot self-host, etc.) may 400 on the
        # unknown param, so only request it for first-party routes. Usage is
        # estimated below when a provider doesn't report it in-stream.
        if provider.type != "openai_compat":
            kwargs["stream_usage"] = True

        collected: list[str] = []
        prompt_t = completion_t = total_t = 0
        reported = False
        stream = litellm.completion(**kwargs)
        for chunk in stream:
            delta = None
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError, TypeError):
                delta = None
            if delta:
                collected.append(delta)
                yield StreamEvent(delta, "", 0, 0, 0, done=False)
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                prompt_t = getattr(usage, "prompt_tokens", 0) or 0
                completion_t = getattr(usage, "completion_tokens", 0) or 0
                total_t = getattr(usage, "total_tokens", None) or (prompt_t + completion_t)
                reported = True

        content = "".join(collected)
        if not reported:
            prompt_t = _estimate_tokens(" ".join(m.get("content", "") for m in messages))
            completion_t = _estimate_tokens(content)
            total_t = prompt_t + completion_t
        self._record_usage(provider, model_id, request_kind, ref_id, prompt_t, completion_t, total_t)
        yield StreamEvent(None, content, prompt_t, completion_t, total_t, done=True)

    def embed(
        self,
        provider: Provider,
        model_id: str,
        inputs: list[str],
        request_kind: str = "embedding",
        ref_id: str | None = None,
    ) -> list[list[float]]:
        """Embed texts via the provider's OpenAI-compatible embeddings API.

        This is the RAG path: a dedicated embedding model (e.g. a free SiliconFlow
        bge model, OpenAI text-embedding-3-small, ...) configured with the
        ``embedding`` role. Anthropic offers no embeddings API and raises here.
        Inputs are batched to keep payloads small; usage is recorded per batch.
        """
        if provider.type == "anthropic":
            raise ValueError(
                "the embedding role requires an OpenAI-compatible provider; "
                "Anthropic offers no embeddings API"
            )
        base_kwargs: dict[str, Any] = {
            "model": f"openai/{model_id}",
            "api_key": self._api_key(provider),
        }
        if provider.type == "openai_compat" and provider.base_url:
            base_kwargs["api_base"] = provider.base_url

        out: list[list[float]] = []
        batch = 32
        for i in range(0, len(inputs), batch):
            resp = litellm.embedding(**base_kwargs, input=inputs[i : i + batch])
            usage = getattr(resp, "usage", None)
            prompt_t = getattr(usage, "prompt_tokens", 0) or 0
            total_t = getattr(usage, "total_tokens", None) or prompt_t
            self._record_usage(provider, model_id, request_kind, ref_id, prompt_t, 0, total_t)
            out.extend(self._embedding_vectors(resp))
        return out

    @staticmethod
    def _embedding_vectors(resp: Any) -> list[list[float]]:
        """Extract embedding vectors from a litellm embedding response."""
        data = getattr(resp, "data", None) or []
        vectors: list[list[float]] = []
        for item in data:
            vec = getattr(item, "embedding", None)
            if vec is None and isinstance(item, dict):
                vec = item.get("embedding")
            if vec is not None:
                vectors.append(list(vec))
        return vectors

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
