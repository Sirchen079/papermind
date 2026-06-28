"""Context-window management for the agent.

Rather than hard-truncating history (which drops facts mid-thought), we
**compact**: when the running conversation approaches the model's context
window, the oldest complete turns are folded into a short running summary by a
separate LLM call, while recent turns and any in-flight tool sequence are kept
verbatim. Falls back to dropping oldest turns if the summarizer fails.
"""
from __future__ import annotations

import json
from typing import Any

# Per-message framing overhead (role tags etc.), in tokens. Rough but stable.
_PER_MSG_OVERHEAD = 4
# Reserved headroom inside the window for the system prompt, tool schemas, RAG
# context, and the response itself.
_RESERVE = 4000
DEFAULT_CONTEXT_WINDOW = 16000

_SUMMARIZE_PROMPT = (
    "Summarize the research conversation below. Preserve: every paper title and "
    "id mentioned, key findings, comparisons, and any conclusions the user or "
    "assistant reached. Be concise (a few sentences / short bullets). Do not "
    "invent details.\n\nConversation:\n"
)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token)."""
    return max(0, len(text or "") // 4)


def _msg_tokens(m: dict[str, Any]) -> int:
    body = m.get("content") or ""
    # tool_calls carry their own JSON payload
    tc = m.get("tool_calls")
    if tc:
        body += json.dumps(tc, ensure_ascii=False)
    return _PER_MSG_OVERHEAD + estimate_tokens(body)


def total_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(_msg_tokens(m) for m in messages)


def compact_history(
    messages: list[dict[str, Any]],
    client: Any,
    provider: Any,
    model_id: str,
    context_window: int | None,
    *,
    keep_recent: int = 6,
) -> list[dict[str, Any]]:
    """Return a token-bounded copy of ``messages``.

    No-op when the conversation fits. Otherwise the system prompt (messages[0])
    stays, the last ``keep_recent`` turns stay verbatim, and everything older is
    summarized into a single system message. A trailing tool sequence is never
    split — if the recent window starts mid-tool, messages are pulled back from
    the older portion until the boundary is clean.
    """
    budget = max(2000, (context_window or DEFAULT_CONTEXT_WINDOW) - _RESERVE)
    if total_tokens(messages) <= budget or len(messages) <= keep_recent + 1:
        return messages

    head = messages[0]
    rest = messages[1:]
    recent = rest[-keep_recent:]
    older = rest[:-keep_recent]
    if not older:
        return messages

    # Don't begin `recent` with a tool result (it must follow its assistant call).
    while recent and recent[0].get("role") == "tool" and older:
        recent.insert(0, older.pop())
    if not older:
        return messages

    transcript = "\n".join(
        f"{m.get('role', '?')}: {(m.get('content') or '')[:500]}" for m in older
    )
    try:
        result = client.complete(
            provider,
            model_id,
            [{"role": "user", "content": _SUMMARIZE_PROMPT + transcript[:6000]}],
            request_kind="chat",
        )
        summary = (result.content or "").strip()
    except Exception:  # noqa: BLE001 — compaction is best-effort
        summary = ""

    if summary:
        compacted = [
            head,
            {"role": "system", "content": f"Summary of earlier in this conversation:\n{summary}"},
            *recent,
        ]
        if total_tokens(compacted) < total_tokens(messages):
            return compacted
    # Fallback: drop the oldest turns outright.
    return [head, *recent]
