"""The agent loop — a tool-calling harness.

Each iteration: ask the model (with tools available) → if it returns tool
calls, execute them, feed the results back, and loop; if it returns text, that
is the answer. Emits events so the UI can show what the agent is doing:

  ("tool",  {"name", "args", "result", "ok"})   — a tool was called
  ("delta", {"content"})                        — (final) answer text
  ("done",  {"content"})                        — terminal
  ("error", {"message"})                        — unrecoverable failure
  ("ask_user", {"request", "state", "tokens"})  — suspend until a human answers

If the provider rejects tools entirely (some ``openai_compat`` gateways), the
loop degrades to a single plain completion so the assistant still answers.
"""
from __future__ import annotations

import json
from app.agent.attachments import text_content
from collections.abc import Iterator
from typing import Any

from app.agent.context import compact_history, total_tokens, DEFAULT_CONTEXT_WINDOW
from app.agent.tools import get_tool, tool_schemas
from app.agent.clarification import question_request
from app.agent.provenance import tool_sources
from app.agent.evidence_review import review_answer

MAX_ITERS = 100


def _tools_unsupported(exc: Exception) -> bool:
    """Only downgrade for an explicit tool-capability rejection."""
    status = getattr(exc, 'status_code', None)
    if status is not None and status not in {400, 404, 422, 501}:
        return False
    message = str(exc).lower()
    return ('tool' in message or 'function_call' in message) and any(
        marker in message for marker in ('not support', 'unsupported', 'not allowed', 'unrecognized', 'unknown parameter')
    )


def _assistant_msg(turn: Any) -> dict[str, Any]:
    """Reconstruct the assistant turn to append back into the message history."""
    msg: dict[str, Any] = {"role": "assistant", "content": turn.content or ""}
    if getattr(turn,'reasoning_content',None):
        msg['reasoning_content']=turn.reasoning_content
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
    evidence_context: str | None = None,
    cancelled=None,
    continuation: dict | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield agent events until a final answer or the step limit."""
    schemas = tool_schemas()
    use_tools = bool(schemas)
    msgs = list(messages)
    tokens_used = (continuation or {}).get("tokens", 0)
    partial_full_text = (continuation or {}).get("partial_full_text", False)
    coverage_checked = (continuation or {}).get("coverage_checked", False)
    evidence=[{'text':evidence_context,'coverage':'provided context; distinguish original excerpts and notes'}] if evidence_context else []
    if continuation and continuation.get('evidence'):
        evidence = continuation['evidence']
    question=next((text_content(m.get('content','')).split('[本轮用户问题]\n')[-1] for m in reversed(messages) if m.get('role')=='user'),'')

    for _ in range(max_iters):
        if cancelled is not None and cancelled.is_set():
            yield ("error", {"message": "已停止，不再执行后续工具调用。"})
            return
        yield ("status", {"phase": "thinking", "step": _ + 1, "max_steps": max_iters, "model": model_id})
        before = total_tokens(msgs)
        original = msgs
        msgs = compact_history(msgs, client, provider, model_id, context_window)
        yield ("status", {"phase": "thinking", "step": _ + 1, "max_steps": max_iters, "model": model_id,
                          "context": {"before": before, "after": total_tokens(msgs),
                                      "window": context_window or DEFAULT_CONTEXT_WINDOW,
                                      "compacted": msgs is not original,
                                      "summarized": msgs is not original and any(
                                          m.get("role") == "system" and str(m.get("content", "")).startswith("Summary of earlier in this conversation:")
                                          for m in msgs[1:])}})
        if cancelled is not None and cancelled.is_set():
            yield ("error", {"message": "已停止，不再执行后续工具调用。"})
            return
        try:
            turn = client.complete_with_tools(
                provider, model_id, msgs, "chat", tools=schemas if use_tools else None
            )
        except Exception as exc:  # noqa: BLE001
            if use_tools and _tools_unsupported(exc):
                use_tools = False
                continue
            yield ("error", {"message": str(exc)})
            return
        if cancelled is not None and cancelled.is_set():
            yield ("error", {"message": "已停止，不再执行后续工具调用。"})
            return
        tokens_used += turn.total_tokens

        if use_tools and turn.tool_calls:
            msgs.append(_assistant_msg(turn))
            questions = [tc for tc in turn.tool_calls if tc.name == "ask_user"]
            if questions:
                # A clarification barrier precedes ALL calls in a mixed batch,
                # including mutations placed before ask_user by the model.
                pending = questions[0]
                try:
                    request = question_request(pending.arguments)
                    error = None
                except ValueError as exc:
                    request, error = None, f"ask_user 参数无效：{exc}"
                for tc in turn.tool_calls:
                    if tc.id == pending.id and error is None:
                        continue
                    result = error if tc.id == pending.id else "未执行：请先完成本轮用户澄清。如仍需该工具，收到用户回复后重新调用。"
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    yield ("tool", {"name": tc.name, "args": tc.arguments, "result": result, "ok": False})
                if error is not None:
                    continue
                yield ("ask_user", {"request": request,
                    "state": {"messages": msgs, "tool_call_id": pending.id, "evidence": evidence, "tokens": tokens_used, "partial_full_text": partial_full_text, "coverage_checked": coverage_checked}, "tokens": tokens_used})
                return
            for tc in turn.tool_calls:
                if cancelled is not None and cancelled.is_set():
                    yield ("error", {"message": "已停止，不再执行后续工具调用。"})
                    return
                yield ("status", {"phase": "tool", "name": tc.name, "step": _ + 1, "max_steps": max_iters})
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
                sources = tool_sources(session, tc.name, result) if ok else []
                if ok and tc.name == 'get_paper_full_text':
                    try:
                        partial_full_text |= bool(json.loads(result).get('truncated'))
                    except (ValueError, AttributeError):
                        pass
                if sources or (ok and tc.name=='get_paper_full_text'):
                    evidence.append({'text':json.dumps({'tool':tc.name,'arguments':tc.arguments,'result':result},ensure_ascii=False),'coverage':'actual tool execution; result may be metadata or an excerpt'})
                yield ("tool", {"name": tc.name, "args": tc.arguments, "result": result[:800], "ok": ok, "sources": sources})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue

        # No tool calls (or tools disabled) → terminal answer.
        if use_tools and partial_full_text and not coverage_checked and _ < max_iters - 1:
            # A truthful "not in this excerpt" is still incomplete if a requested
            # fact can be located in the available paper. Give the agent one
            # bounded retrieval checkpoint before evidence review/publication.
            coverage_checked = True
            msgs.append(_assistant_msg(turn))
            msgs.append({'role': 'user', 'content':
                '回答前检索完整性检查：你读取的全文仍是局部片段。逐项核对原问题所要求的事实；'
                '若还有仅因当前片段缺失而未回答的项目，请用 get_paper_full_text 的 query 定位其他章节，'
                '必要时用 start_char 翻页，不要把可继续检索的问题提前交还用户。'
                '若所有请求已回答或材料确实不可取得，可直接给出最终答案。不要编造缺项；本检查只执行一次。'})
            continue
        content = turn.content or ""
        if not content.strip():
            yield ("error", {"message": "模型未返回回答内容，原问题已保留，可以重试。"})
            return
        yield ("status", {"phase": "review", "step": _ + 1, "max_steps": max_iters})
        try:
            content,review_tokens,audit=review_answer(client,provider,model_id,question,content,evidence,context_window)
            tokens_used+=review_tokens
        except Exception as exc:
            yield ('error',{'message':str(exc)})
            return
        if cancelled is not None and cancelled.is_set():
            yield ('error', {'message': '已停止，原问题已保留。'})
            return
        yield ("delta", {"content": content, "tokens": tokens_used})
        yield ("done", {"content": content, "tokens": tokens_used,'evidence_review':audit})
        return

    # Exhausted the step budget without a plain answer.
    yield ("error", {"message": "已到本轮调用上限，进度已保存。点击继续可从已有工具结果接着处理。",
        "continuable": True, "state": {"messages": msgs, "evidence": evidence, "tokens": tokens_used, "partial_full_text": partial_full_text, "coverage_checked": coverage_checked}})
