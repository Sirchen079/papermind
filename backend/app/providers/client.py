from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
from typing import Any

import litellm
from sqlmodel import Session, select

from app.models import Model, Provider, TokenUsage
from app.agent.attachments import responses_content
from app.providers.routing import anthropic_api_base, route_completion
from app.providers.capabilities import reasoning_options
from app.providers.prompt_cache import cache_options, cache_usage, marker_count, prepare_messages, prepare_tools, token_usage
from app.security.crypto import Crypto
from app.security.url_guard import ensure_http_url, validated_get


DEFAULT_REASONING_EFFORT = 'high'  # 卡 24：未设置时的思考等级；基准为 glm-5.3（max）


def _generation_timeout(api_base, effort):
    """Use the same generation allowance for document writing and tool agents."""
    import httpx
    from app.providers.local import is_loopback_url
    if is_loopback_url(api_base):
        return httpx.Timeout(None, connect=10, write=60, pool=60)
    if effort in {'medium', 'high', 'xhigh', 'max'}:
        # max 推理一次可能产出几万 token，读超时按基准档位 glm-5.3(max) 留足。
        read = {'medium': 300, 'high': 600, 'xhigh': 1200, 'max': 1200}[effort]
        return httpx.Timeout(read, connect=10, write=60, pool=60)
    return 180


def _review_generation_timeout(api_base, effort):
    """Review chapters emit ~3500 tokens over long inputs; slow remote models
    missed the old 180s cap, so only library_review waits up to 900s (1800s
    when the effective effort is xhigh/max). Loopback keeps the unlimited
    read timeout."""
    import httpx
    from app.providers.local import is_loopback_url
    if is_loopback_url(api_base):
        return _generation_timeout(api_base, effort)
    return httpx.Timeout(1800 if effort in {'xhigh', 'max'} else 900,
                         connect=10, write=60, pool=60)


class EmptyResponseError(ValueError):
    """The provider consumed a call but supplied no final assistant text."""

    def __init__(self, message, *, output_exhausted=False):
        super().__init__(message)
        self.output_exhausted = output_exhausted


@dataclass
class CompletionResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_usage_reported: bool = False
    output_incomplete: bool = False
    output_exhausted: bool = False


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolTurn:
    """One agent-loop step: assistant text and/or a batch of tool calls."""

    content: str
    tool_calls: list[ToolCall]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_content: str | None = None  # Private protocol state, never user-facing answer text.


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
    def value(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    text = value(resp, "output_text")
    if isinstance(text, str) and text:
        return text
    parts: list[str] = []
    for item in value(resp, "output", []) or []:
        if value(item, "type") != "message":
            continue
        content = value(item, "content")
        if isinstance(content, list):
            for block in content:
                t = value(block, "text")
                if value(block, "type") == "output_text" and isinstance(t, str):
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
        from app.providers.shared import application_dir
        self._application_dir = application_dir()

    def _ready_provider(self, provider):
        from app.providers.managed import manager, model_id
        mid = model_id(provider.base_url)
        if not mid:
            return provider
        url, key = manager(self._application_dir).ready(mid)
        return provider.model_copy(update={'base_url':url, 'api_key_encrypted':self._crypto.encrypt(key)})

    def _api_key(self, provider: Provider) -> str | None:
        if not provider.api_key_encrypted:
            from app.providers.local import is_loopback_url
            if provider.type in {'openai_chat', 'openai_responses', 'openai_compat'} and is_loopback_url(provider.base_url):
                # OpenAI clients require a value even when a local server does
                # not authenticate. Do not inherit an unrelated cloud API key.
                return 'papermind-local'
            return None
        return self._crypto.decrypt(provider.api_key_encrypted)

    def _configured_effort(self, provider: Provider, model_id: str) -> str | None:
        """The user-configured thinking level on the model row, if any.

        Resolved here — the single choke point both completion entry points
        share — so every call path (chat agent, wiki, research, evidence
        review) honors the setting without per-caller plumbing. A DB hiccup
        or unknown value must not fail the LLM call: fall back to None.
        """
        try:
            with self._session_factory() as session:
                row = session.exec(
                    select(Model).where(
                        Model.provider_id == provider.id, Model.model_id == model_id
                    )
                ).first()
                effort = getattr(row, "reasoning_effort", None)
                return effort if effort in {"low", "medium", "high", "xhigh", "max"} else None
        except Exception:
            return None

    def effective_effort(self, provider: Provider, model_id: str) -> str:
        """The effort callers should budget and plan around: the user's setting, else the default."""
        return self._configured_effort(provider, model_id) or DEFAULT_REASONING_EFFORT

    def _resolve_effort(self, provider: Provider, model_id: str, route, requested: str | None):
        """One choke point shared by every completion entry point (卡 24).

        Precedence: the user-configured level, then the caller's value, then
        DEFAULT_REASONING_EFFORT. Documented vendors (official GLM) get their
        translated request params; undocumented models only receive a thinking
        knob when the SDK knows they support reasoning or the user set one.
        Returns ``(request kwargs, effective effort)``; the effective effort
        (None when no thinking params are sent) drives timeout selection.
        """
        configured = self._configured_effort(provider, model_id)
        effort = configured or requested or DEFAULT_REASONING_EFFORT
        documented = reasoning_options(provider, model_id, effort)
        if documented:
            return dict(documented), effort
        if not configured:
            try:
                if not litellm.supports_reasoning(model=route.litellm_model):
                    return {}, None
            except Exception:
                return {}, None
        if route.call == 'responses':
            return {'reasoning': {'effort': effort}}, effort
        return {'reasoning_effort': effort}, effort

    def complete(
        self,
        provider: Provider,
        model_id: str,
        messages: list[dict[str, Any]],
        request_kind: str,
        ref_id: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> CompletionResult:
        provider = self._ready_provider(provider)
        route = route_completion(provider.type, model_id, provider.base_url)
        thinking, effective_effort = self._resolve_effort(provider, model_id, route, reasoning_effort)
        kwargs: dict[str, Any] = {
            "model": route.litellm_model,
            "messages": prepare_messages(messages, provider.type, request_kind, marker_budget=4),
            "api_key": self._api_key(provider),
        }
        kwargs.update(cache_options(provider.type, route.api_base, request_kind, kwargs['messages']))
        kwargs.update(thinking)
        if route.api_base:
            kwargs["api_base"] = ensure_http_url(route.api_base)  # SSRF guard

        # No unbounded provider retries inside a bounded research step.
        if request_kind in {"research", "rerank_llm", "retrieval_query"}:
            kwargs["timeout"] = 90 if request_kind == 'research' else 45
            kwargs["num_retries"] = 0
            if effective_effort in {'medium', 'high', 'xhigh', 'max'}:
                scaled = _generation_timeout(route.api_base, effective_effort)
                if scaled.read is not None:  # loopback keeps the original fixed bound
                    kwargs['timeout'] = scaled
        elif request_kind in {"evidence_review", "wiki_update", "pdf_ocr", "library_review"}:
            # LiteLLM's inherited default can be 6000 seconds. Bound a
            # foreground step and let the application expose a retryable error.
            kwargs["timeout"] = 300 if request_kind == "evidence_review" else 180
            kwargs["num_retries"] = 0
            if request_kind == 'evidence_review' and effective_effort in {'medium', 'high', 'xhigh', 'max'}:
                read = _generation_timeout(route.api_base, effective_effort).read
                if read is not None:  # loopback stays at the fixed 300s
                    kwargs['timeout'] = max(300, read)
            if request_kind == 'library_review':
                kwargs['timeout'] = _review_generation_timeout(route.api_base, effective_effort)
        if route.call == "responses":
            kwargs["input"] = [{**m, "content": responses_content(m.get("content"))} for m in kwargs.pop("messages")]
            if max_tokens is not None:
                kwargs["max_output_tokens"] = max_tokens
            resp = litellm.responses(**kwargs)
            content = _responses_text(resp)
            usage = getattr(resp, "usage", None)
        else:
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            resp = litellm.completion(**kwargs)
            content = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)

        prompt_t, completion_t, total_t = token_usage(usage)

        self._record_usage(provider, model_id, request_kind, ref_id, prompt_t, completion_t, total_t, usage=usage)
        incomplete = getattr(resp, 'status', None) == 'incomplete' if route.call == 'responses' else getattr(resp.choices[0], 'finish_reason', None) == 'length'
        details = getattr(resp, 'incomplete_details', None)
        reason = details.get('reason') if isinstance(details, dict) else getattr(details, 'reason', None)
        exhausted = incomplete and (route.call != 'responses' or reason == 'max_output_tokens')
        if request_kind in {'pdf_ocr', 'rerank_llm'}:
            if incomplete:
                raise ValueError('OCR output truncated' if request_kind == 'pdf_ocr' else 'Reranking output truncated')
        if not content.strip() and (route.call == "responses" or exhausted):
            raise EmptyResponseError("模型未返回最终文本；可能达到输出上限，不能当作任务完成",
                                     output_exhausted=exhausted)
        return CompletionResult(content, prompt_t, completion_t, total_t, *cache_usage(usage),
                                output_incomplete=incomplete, output_exhausted=exhausted)

    def rerank(self, provider, model_id, query, documents, top_n):
        """SiliconFlow / Jina-compatible rerank protocol, separate from chat."""
        import httpx
        provider = self._ready_provider(provider)
        url = ensure_http_url(provider.base_url.rstrip('/') + '/rerank')
        headers = json.loads(provider.extra_headers_json or '{}')
        key = self._api_key(provider)
        if key:
            headers['Authorization'] = f'Bearer {key}'
        response = httpx.post(url, headers=headers, json={
            'model': model_id, 'query': query, 'documents': documents,
            'top_n': min(top_n, len(documents)), 'return_documents': False,
        }, timeout=20, follow_redirects=False)
        response.raise_for_status()
        data = response.json()
        ranked, seen = [], set()
        for row in data.get('results', []):
            idx, score = row.get('index'), row.get('relevance_score')
            if type(idx) is not int or not 0 <= idx < len(documents) or idx in seen:
                raise ValueError('Invalid rerank index')
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError('Invalid rerank score')
            seen.add(idx)
            ranked.append((idx, float(score)))
        if len(ranked) < min(top_n, len(documents)):
            raise ValueError('Incomplete rerank response')
        usage = data.get('usage')
        if usage:
            p, c, total = token_usage(usage)
            self._record_usage(provider, model_id, 'rerank', None, p, c, total, usage=usage)
        return sorted(ranked, key=lambda item: item[1], reverse=True)[:top_n]

    def complete_with_tools(
        self,
        provider: Provider,
        model_id: str,
        messages: list[dict[str, Any]],
        request_kind: str,
        tools: list[dict[str, Any]] | None = None,
        ref_id: str | None = None,
    ) -> ToolTurn:
        """Completion that may return tool calls (the agent loop's per-step call).

        Preserve the configured protocol, translating tool messages for Responses.
        ``tools`` uses the existing chat function schema at the agent boundary.
        """
        provider = self._ready_provider(provider)
        route = route_completion(provider.type, model_id, provider.base_url)
        kwargs: dict[str, Any] = {
            "model": route.litellm_model,
            "messages": prepare_messages(messages, provider.type, request_kind, max(0, 4 - (max(1, marker_count(tools)) if tools else 0))),
            "api_key": self._api_key(provider),
            "timeout": 180,
            "num_retries": 0,
        }
        if route.api_base:
            # SSRF guard: api_base comes from user-configured base_url and
            # LiteLLM builds the outbound chat/responses URL from it. Only
            # http(s) with a host may leave the process; otherwise raise
            # ValueError before any request (callers map it to 4xx/502).
            kwargs["api_base"] = ensure_http_url(route.api_base)
        if tools:
            kwargs["tools"] = prepare_tools(tools, kwargs['messages'], provider.type)
            kwargs["tool_choice"] = "auto"

        kwargs.update(cache_options(provider.type, route.api_base, request_kind, kwargs['messages']))
        thinking, effective_effort = self._resolve_effort(provider, model_id, route, None)
        kwargs['timeout'] = _generation_timeout(route.api_base, effective_effort)
        kwargs.update(thinking)
        if route.call == "responses":
            converted = []
            for message in kwargs['messages']:
                if message.get("role") == "tool":
                    converted.append({"type":"function_call_output","call_id":message["tool_call_id"],"output":message.get("content","")})
                    continue
                if message.get("content"):
                    converted.append({"role":message["role"],"content":responses_content(message["content"])})
                for call in message.get("tool_calls",[]) or []:
                    converted.append({"type":"function_call","call_id":call["id"],"name":call["function"]["name"],"arguments":call["function"]["arguments"]})
            kwargs.pop("messages")
            kwargs["input"] = converted
            if tools:
                kwargs["tools"] = [{"type":"function",**tool["function"]} for tool in tools]
            resp = litellm.responses(**kwargs)
            output = getattr(resp,"output",[]) or []
            tool_calls = []
            for item in output:
                val = item.get if isinstance(item,dict) else lambda key,default=None: getattr(item,key,default)
                if val("type") != "function_call":
                    continue
                try:
                    arguments = json.loads(val("arguments","{}"))
                except (TypeError,ValueError):
                    arguments = {}
                tool_calls.append(ToolCall(id=val("call_id","") or val("id",""),name=val("name",""),arguments=arguments if isinstance(arguments,dict) else {}))
            usage = getattr(resp,"usage",None)
            prompt_t, completion_t, total_t = token_usage(usage)
            self._record_usage(provider,model_id,request_kind,ref_id,prompt_t,completion_t,total_t,usage=usage)
            content = _responses_text(resp)
            if not tool_calls and not content.strip():
                raise ValueError("Responses 未返回最终文本或工具请求")
            return ToolTurn(content,tool_calls,prompt_t,completion_t,total_t)

        resp = litellm.completion(**kwargs)
        msg = resp.choices[0].message
        content = getattr(msg, "content", None) or ""
        tool_calls: list[ToolCall] = []
        for tc in getattr(msg, "tool_calls", None) or []:
            raw_args = getattr(tc.function, "arguments", "{}") or "{}"
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed = {}
            tool_calls.append(
                ToolCall(
                    id=getattr(tc, "id", "") or "",
                    name=getattr(tc.function, "name", "") or "",
                    arguments=parsed,
                )
            )

        usage = getattr(resp, "usage", None)
        prompt_t, completion_t, total_t = token_usage(usage)
        self._record_usage(provider, model_id, request_kind, ref_id, prompt_t, completion_t, total_t, usage=usage)
        return ToolTurn(content, tool_calls, prompt_t, completion_t, total_t,getattr(msg,'reasoning_content',None))

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
        provider = self._ready_provider(provider)
        route = route_completion(provider.type, model_id, provider.base_url)
        kwargs: dict[str, Any] = {
            "model": route.litellm_model,
            "messages": prepare_messages(messages, provider.type, request_kind, marker_budget=4),
            "api_key": self._api_key(provider),
        }
        if route.api_base:
            kwargs["api_base"] = ensure_http_url(route.api_base)  # SSRF guard

        if route.call == "responses":
            result = self.complete(provider, model_id, messages, request_kind, ref_id)
            yield StreamEvent(result.content, result.content, result.prompt_tokens,
                              result.completion_tokens, result.total_tokens, done=True)
            return

        kwargs.update(cache_options(provider.type, route.api_base, request_kind, kwargs['messages']))
        # 卡 24：流式对话同样走用户设置/默认等级，并按生效等级选超时。
        thinking, effective_effort = self._resolve_effort(provider, model_id, route, None)
        kwargs.update(thinking)
        kwargs['timeout'] = _generation_timeout(route.api_base, effective_effort)
        kwargs["stream"] = True
        # stream_usage is an OpenAI chat-completions extension. Conservative
        # openai_compat gateways (DeepSeek/智谱/Moonshot self-host, etc.) and
        # the Anthropic provider don't accept it (Anthropic reports usage via a
        # separate stream block), so only request it on first-party OpenAI
        # routes. Usage is estimated below when a provider doesn't report it
        # in-stream.
        if provider.type in {"openai_chat", "openai_responses"}:
            kwargs["stream_options"] = {"include_usage": True}

        collected: list[str] = []
        prompt_t = completion_t = total_t = 0
        reported = False
        last_usage = None
        cached_t = written_t = 0
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
                # Some streams separate input/cache metadata from the final
                # output counter. Preserve both instead of losing cache hits.
                p, c, t = token_usage(usage)
                prompt_t, completion_t = max(prompt_t, p), max(completion_t, c)
                total_t = max(total_t, t, prompt_t + completion_t)
                read, written, known = cache_usage(usage)
                cached_t, written_t = max(cached_t, read), max(written_t, written)
                if known or last_usage is not None:
                    last_usage = {'prompt_tokens_details': {'cached_tokens': cached_t, 'cache_write_tokens': written_t}}
                reported = True

        content = "".join(collected)
        if not reported:
            prompt_t = _estimate_tokens(" ".join(m.get("content", "") if isinstance(m.get("content"), str) else json.dumps(m.get("content") or '', ensure_ascii=False) for m in messages))
            completion_t = _estimate_tokens(content)
            total_t = prompt_t + completion_t
        self._record_usage(provider, model_id, request_kind, ref_id, prompt_t, completion_t, total_t, usage=last_usage)
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
        cache_provider = provider
        provider = self._ready_provider(provider)
        if provider.type == "anthropic":
            raise ValueError(
                "the embedding role requires an OpenAI-compatible provider; "
                "Anthropic offers no embeddings API"
            )
        base_kwargs: dict[str, Any] = {
            "model": f"openai/{model_id}",
            "api_key": self._api_key(provider),
            # LiteLLM defaults ``encoding_format`` to None and still serializes
            # it into the request body as JSON ``null``. Strict OpenAI-compatible
            # gateways (e.g. SiliconFlow) reject that null with a 400 "parameter
            # invalid", silently breaking every embedding call. ``"float"`` is the
            # OpenAI default value, so any compatible endpoint accepts it.
            "encoding_format": "float",
        }
        if provider.base_url:
            # SSRF guard: same rule as every other base_url-derived endpoint.
            base_kwargs["api_base"] = ensure_http_url(provider.base_url)

        # Embeddings are deterministic inputs too. Re-indexing unchanged chunks
        # and repeated retrieval queries should not pay for identical vectors.
        from app.research import cache
        with self._session_factory() as session:
            cache_engine = session.get_bind()
        out: list[list[float]] = []
        batch = 32
        for i in range(0, len(inputs), batch):
            texts = inputs[i:i+batch]
            keys = [cache.cache_key(cache_provider, model_id, text, 'embedding-float-v1') for text in texts]
            batch_key = cache.cache_key(cache_provider, model_id, sorted(set(keys)), 'embedding-batch')
            with cache.key_lock(batch_key):
                vectors = {}
                missing = {}
                for key, text in zip(keys, texts):
                    stored = cache.read(cache_engine, key)
                    vector = stored.get('vector') if isinstance(stored, dict) else None
                    if isinstance(vector, list) and vector and all(isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n) for n in vector):
                        vectors[key] = vector
                    else:
                        missing[key] = text
                if missing:
                    resp = litellm.embedding(**base_kwargs, input=list(missing.values()))
                    usage = getattr(resp, "usage", None)
                    prompt_t = getattr(usage, "prompt_tokens", 0) or 0
                    total_t = getattr(usage, "total_tokens", None) or prompt_t
                    self._record_usage(provider, model_id, request_kind, ref_id, prompt_t, 0, total_t)
                    received = self._embedding_vectors(resp)
                    if len(received) != len(missing) or any(not v or not all(isinstance(n,(int,float)) and math.isfinite(n) for n in v) for v in received):
                        raise ValueError('Embedding response has missing or invalid vectors')
                    for key, vector in zip(missing, received):
                        vectors[key] = vector
                        cache.write(cache_engine, key, {'vector':vector})
                out.extend(vectors[key] for key in keys)
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
        usage: Any = None,
    ) -> None:
        cached, written, reported = cache_usage(usage)
        with self._session_factory() as session:
            session.add(
                TokenUsage(
                    provider_id=provider.id,
                    model=model_id,
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                    cached_input_tokens=cached,
                    cache_write_tokens=written,
                    cache_usage_reported=reported,
                    request_kind=request_kind,
                    ref_id=ref_id,
                    day=_utc_date(),
                )
            )
            session.commit()

    def list_models(self, provider: Provider) -> list[ModelInfo]:
        url, headers = self._models_endpoint(provider)
        resp = validated_get(url, headers=headers, timeout=30.0)
        # Raise on auth/quota/etc. failures BEFORE parsing: an error body like
        # {"error": {...}} has no "data" list, and without this guard the loop
        # below would iterate dict *keys* and raise AttributeError (a confusing
        # 500 instead of the caller's clean 502).
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data,dict) and (data.get("success") is False or data.get("error")):
            raise ValueError("模型列表接口返回错误，请检查提供商配置")
        raw = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise ValueError("Model endpoint did not return a model list")
        out: list[ModelInfo] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            mid = item.get("id") or item.get("slug") or item.get("model") or item.get("name")
            if not mid:
                continue
            out.append(ModelInfo(model_id=mid, display_name=item.get("display_name") or mid, context_window=item.get("context_window")))
        return out

    def _models_endpoint(self, provider: Provider) -> tuple[str, dict[str, str]]:
        provider = self._ready_provider(provider)
        key = self._api_key(provider)
        if provider.type in {"openai_chat", "openai_responses", "openai_compat"}:
            base = ensure_http_url(
                (provider.base_url or "https://api.openai.com/v1").rstrip("/")
            )
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            return f"{base}/models", headers
        if provider.type == "anthropic":
            # Anthropic's List Models API: GET /v1/models -> {data:[{id,...}],
            # has_more, first_id, last_id}. Honor a custom base_url (relay/网关)
            # so a Claude-format proxy actually works; fall back to the official
            # host only when none is set. ?limit=1000 pulls the full catalog in
            # one page (default page size is 20).
            base = ensure_http_url(
                anthropic_api_base(provider.base_url) or "https://api.anthropic.com"
            )
            return f"{base}/v1/models?limit=1000", {
                "x-api-key": key or "",
                "anthropic-version": "2023-06-01",
            }
        raise ValueError(f"no models endpoint for type {provider.type}")
