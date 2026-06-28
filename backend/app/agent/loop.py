"""The agent loop — a tool-calling harness.

Each iteration: ask the model (with tools available) → if it returns tool
calls, execute them, feed the results back, and loop; if it returns text, that
is the answer. Emits events so the UI can show what the agent is doing:

  ("tool",  {"name", "args", "result", "ok"})   — a tool was called
  ("delta", {"content"})                        — (final) answer text
  ("done",  {"content"})                        — terminal
  ("error", {"message"})                        — unrecoverable failure

If the provider rejects tools entirely (some ``openai_compat`` gateways), the
loop degrades to a single plain completion so the assistant still answers.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from app.agent.context import compact_history
from app.agent.tools import get_tool, tool_schemas

MAX_ITERS = 8


def _assistant_msg(turn: Any) -> dict[str, Any]:
    """Reconstruct the assistant turn to append back into the message history."""
    msg: dict[str, Any] = {"role": "assistant", "content": turn.content or ""}
    if turn.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in turn.tool_calls
        ]
    return msg


def run_agent(
    client: Any,
    provider: Any,
    model_id: str,
    messages: list[dict[str, Any]],
    session: Any,
    *,
    context_window: int | None = None,
    max_iters: int = MAX_ITERS,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield agent events until a final answer or the step limit."""
    schemas = tool_schemas()
    use_tools = bool(schemas)
    msgs = list(messages)
    tokens_used = 0

    for _ in range(max_iters):
        msgs = compact_history(msgs, client, provider, model_id, context_window)
        try:
            turn = client.complete_with_tools(
                provider, model_id, msgs, "chat", tools=schemas if use_tools else None
            )
        except Exception as exc:  # noqa: BLE001
            if use_tools:
                # Provider likely doesn't support tool calling — retry plain.
                use_tools = False
                continue
            yield ("error", {"message": str(exc)})
            return
        tokens_used += turn.total_tokens

        if use_tools and turn.tool_calls:
            msgs.append(_assistant_msg(turn))
            for tc in turn.tool_calls:
                tool = get_tool(tc.name)
                if tool is None:
                    result, ok = f"unknown tool: {tc.name}", False
                else:
                    # Only forward declared parameters — a model that invents an
                    # extra kwarg would otherwise TypeError and waste the turn.
                    allowed = set((tool.parameters.get("properties") or {}).keys())
                    call_args = {k: v for k, v in tc.arguments.items() if k in allowed}
                    try:
                        result = tool.run(session, **call_args)
                        ok = True
                    except Exception as exc:  # noqa: BLE001 — one bad tool shouldn't kill the loop
                        result, ok = f"tool error: {exc}", False
                yield ("tool", {"name": tc.name, "args": tc.arguments, "result": result[:800], "ok": ok})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue

        # No tool calls (or tools disabled) → terminal answer.
        content = turn.content or ""
        yield ("delta", {"content": content, "tokens": tokens_used})
        yield ("done", {"content": content, "tokens": tokens_used})
        return

    # Exhausted the step budget without a plain answer.
    yield ("done", {"content": "我已经达到本轮工具调用的步数上限，但未能给出最终回答——能否换个说法或缩小问题范围？", "tokens": tokens_used})
