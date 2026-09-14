"""Context-window management for the agent.

Rather than hard-truncating history (which drops facts mid-thought), we
**compact**: when the running conversation approaches the model's context
window, the oldest complete turns are folded into a short running summary by a
separate LLM call, while recent turns and any in-flight tool sequence are kept
verbatim. Falls back to dropping oldest turns if the summarizer fails.
"""
from __future__ import annotations

import json
import math
from typing import Any

# Per-message framing overhead (role tags etc.), in tokens. Rough but stable.
_PER_MSG_OVERHEAD = 4
# Reserved headroom inside the window for the system prompt, tool schemas, RAG
# context, and the response itself.
_RESERVE = 4000
DEFAULT_CONTEXT_WINDOW = 16000

_SUMMARIZE_PROMPT = (
    "请用简体中文总结下面的科研对话。需要保留：提到的每一篇论文标题与 id、关键结论、"
    "对比要点，以及用户或助手达成的任何结论。力求简洁（几句话或简短要点）。不要编造细节。\n\n对话：\n"
)


def estimate_tokens(text: str) -> int:
    """Conservative local estimate for mixed Chinese/English; no network fetch."""
    return math.ceil(sum(0.25 if ord(c)<128 else 3 if ord(c)>0xffff else 1.5 for c in (text or '')))


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
    window = context_window or DEFAULT_CONTEXT_WINDOW
    budget = max(256, window - min(_RESERVE, window // 4))
    if total_tokens(messages) <= budget:
        return messages

    head = messages[0]
    rest = messages[1:]
    recent = rest[-keep_recent:]
    older = rest[:-keep_recent]
    # Keep complete user turns, including every assistant call and tool result.
    while recent and recent[0].get("role") != "user" and older:
        recent.insert(0, older.pop())
    while total_tokens([head,*recent]) > budget:
        boundary=next((i for i,m in enumerate(recent) if i>0 and m.get('role')=='user'),None)
        if boundary is None:
            raise ValueError('本轮问题和材料超出模型上下文容量。请缩短问题或选中文本，或换用上下文更大的模型后重新提问。')
        older.extend(recent[:boundary]);recent=recent[boundary:]
    if not older:
        return messages

    def excerpt(message):
        body = message.get('content') or ''
        context, separator, question = body.rpartition('[本轮用户问题]\n')
        if message.get('role') == 'user' and separator:
            return question[:350] + '\n材料快照：' + context[:150]
        return body[:500]

    transcript = "\n".join(f"{m.get('role', '?')}: {excerpt(m)}" for m in older)[:6000]
    while estimate_tokens(_SUMMARIZE_PROMPT+transcript)>budget and transcript:
        transcript=transcript[:max(0,int(len(transcript)*0.8))]
    try:
        result = client.complete(
            provider,
            model_id,
            [{"role": "user", "content": _SUMMARIZE_PROMPT + transcript}],
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
        if total_tokens(compacted) <= budget:
            return compacted
    # Fallback: drop the oldest turns outright.
    return [head, *recent]
