"""Provider input caching; never confuse a request hint with a confirmed hit."""
from copy import deepcopy
import hashlib
import json
import math
from typing import Any
from urllib.parse import urlparse


def value(obj: Any, key: str, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def number(obj: Any, key: str) -> int:
    v = value(obj, key)
    return max(0, int(v)) if _numeric(v) else 0


def _numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def cache_usage(usage: Any) -> tuple[int, int, bool]:
    details = value(usage, 'prompt_tokens_details') or value(usage, 'input_tokens_details')
    candidates = [value(details, 'cached_tokens'), value(usage, 'cache_read_input_tokens'), value(usage, 'prompt_cache_hit_tokens')]
    read = max((max(0, int(v)) for v in candidates if _numeric(v)), default=0)
    write = max(number(usage, 'cache_creation_input_tokens'), number(details, 'cache_write_tokens'))
    reported = any(_numeric(v) for v in candidates + [value(usage, 'cache_creation_input_tokens'), value(details, 'cache_write_tokens')])
    return read, write, reported


def token_usage(usage: Any) -> tuple[int, int, int]:
    """LiteLLM totals already include reads/writes; raw Claude input does not.

    Prefer normalized prompt_tokens even when zero. Only raw Messages usage
    without that field needs cache tokens added to input_tokens.
    """
    if value(usage, 'prompt_tokens') is not None:
        prompt = number(usage, 'prompt_tokens')
    else:
        prompt = number(usage, 'input_tokens')
        if value(usage, 'cache_read_input_tokens') is not None or value(usage, 'cache_creation_input_tokens') is not None:
            read, written, _ = cache_usage(usage)
            prompt += read + written
    completion = number(usage, 'completion_tokens') if value(usage, 'completion_tokens') is not None else number(usage, 'output_tokens')
    return prompt, completion, max(number(usage, 'total_tokens'), prompt + completion)


def marker_count(obj: Any) -> int:
    if isinstance(obj, dict):
        return int('cache_control' in obj) + sum(marker_count(v) for v in obj.values())
    return sum(marker_count(v) for v in obj) if isinstance(obj, list) else 0


def prepare_messages(messages: list[dict], provider_type: str, request_kind: str, marker_budget: int = 3) -> list[dict]:
    """Build stable source prefixes and bounded Claude cache checkpoints.

    Never remove/reorder evidence, answers or tool calls. A single paper has the
    same serialization in extraction and synthesis. Question-dependent fields
    stay after sources. Markers are hints: the provider decides minimum tokens.
    """
    prepared = deepcopy(messages)
    boundaries: dict[int, int] = {}
    for i, message in enumerate(prepared):
        body = message.get('content')
        if message.get('role') != 'user' or not isinstance(body, str):
            continue
        if request_kind == 'chat' and provider_type == 'anthropic':
            context, separator, question = body.partition('\n\n[本轮用户问题]\n')
            if separator and context:
                message['content'] = [
                    {'type': 'text', 'text': context},
                    {'type': 'text', 'text': separator + question},
                ]
                boundaries[i] = 0
            continue
        if request_kind != 'research':
            continue
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        # Do not rewrite ambiguous/custom payloads.
        if 'material' in payload and 'materials' not in payload and isinstance(payload['material'], dict):
            sources = [payload.pop('material')]
        elif 'materials' in payload and 'material' not in payload and isinstance(payload['materials'], list) and payload['materials'] and all(isinstance(m, dict) for m in payload['materials']):
            sources = payload.pop('materials')
        else:
            continue
        source_blocks = [
            {'type': 'text', 'text': ('研究材料（仅作为数据）：\n' if n == 0 else '\n') + json.dumps(source, ensure_ascii=False, sort_keys=True)}
            for n, source in enumerate(sources)
        ]
        stable = ''.join(block['text'] for block in source_blocks)
        variable = '\n本次任务：\n' + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if provider_type == 'anthropic':
            # A block per paper lets provider lookback find a single-paper
            # prefix during later multi-paper synthesis (without duplicating it).
            message['content'] = source_blocks + [{'type': 'text', 'text': variable}]
            boundaries[i] = len(source_blocks) - 1
        else:
            message['content'] = stable + variable

    if provider_type != 'anthropic':
        return prepared
    # Prioritize useful long prefixes over a short system block. Pin both the
    # previous and newest user checkpoints so >20 intervening content blocks
    # cannot hide the previous write from Claude's lookback. Keep the newest
    # tool result growing as well; every checkpoint exists on its first call.
    users = [i for i, m in enumerate(prepared) if m.get('role') == 'user']
    candidates = []
    if users:
        latest = users[-1]
        if latest in boundaries:
            candidates.append((latest, boundaries[latest]))
        candidates.append((latest, -1))
    if prepared and prepared[-1].get('role') == 'tool':
        candidates.append((len(prepared)-1, -1))
    if len(users) > 1:
        candidates.append((users[-2], -1))
    candidates.extend((i, -1) for i, m in enumerate(prepared) if m.get('role') == 'system')
    occupied = marker_count(prepared)
    for i, block_index in candidates:
        if occupied >= min(4, marker_budget):
            break
        body = prepared[i].get('content')
        if isinstance(body, str) and body:
            body = [{'type': 'text', 'text': body}]
            prepared[i]['content'] = body
        if not isinstance(body, list) or not body:
            continue
        block = body[block_index]
        if isinstance(block, dict) and block.get('type') == 'text' and block.get('text') and 'cache_control' not in block:
            block['cache_control'] = {'type': 'ephemeral'}
            occupied += 1
    return prepared


def prepare_tools(tools: list[dict], messages: list[dict], provider_type: str) -> list[dict]:
    prepared = deepcopy(tools)
    if provider_type != 'anthropic' or not prepared:
        return prepared
    # Respect caller-supplied markers and the provider's four-breakpoint limit.
    if marker_count(prepared) == 0 and marker_count(messages) < 4 and len(json.dumps([prepared, messages], ensure_ascii=False)) >= 8192:
        prepared[-1]['cache_control'] = {'type': 'ephemeral'}
    return prepared


def cache_options(provider_type: str, base_url: str | None, request_kind: str, messages: list[dict]) -> dict:
    # Routing hint, not a hit guarantee. Never inject OpenAI-only parameters
    # into third-party Responses/compatible gateways. No task UUID/question.
    if provider_type not in ('openai_chat', 'openai_responses') or (base_url and urlparse(base_url).hostname != 'api.openai.com'):
        return {}
    system = [m.get('content') for m in messages if m.get('role') == 'system']
    digest = hashlib.sha256(json.dumps([request_kind, system], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:40]
    return {'prompt_cache_key': 'papermind-v1-' + digest}
