"""Unit tests for context compaction (the user's explicit ask: summarize, don't truncate)."""
from app.agent.context import compact_history, total_tokens
from app.providers.client import CompletionResult


class _FakeClient:
    """Captures the summarizer call; controllable via ``summary`` / ``raise``."""

    def __init__(self, summary="folded summary", raise_on_complete=False):
        self._summary = summary
        self._raise = raise_on_complete
        self.complete_calls = 0

    def complete(self, provider, model_id, messages, request_kind, ref_id=None):  # noqa: ANN001
        self.complete_calls += 1
        if self._raise:
            raise RuntimeError("summarizer down")
        return CompletionResult(self._summary, 1, 1, 2)


def _msgs(n, token_each=200):
    """Build a list with a system head + n user/assistant turns, each ~token_each tokens.

    200-token messages are big enough to exceed compaction's 2000-token budget floor
    (``max(2000, ctx - 4000)``) with ~10 turns, so compaction actually triggers.
    """
    word = "x" * (token_each * 4)  # ~token_each tokens per message
    out = [{"role": "system", "content": "system"}]
    for i in range(n):
        out.append({"role": "user", "content": f"{i} {word}"})
        out.append({"role": "assistant", "content": f"a{i} {word}"})
    return out


def test_compact_noop_when_under_budget():
    msgs = _msgs(2)
    client = _FakeClient()
    assert compact_history(msgs, client, object(), "m", context_window=16000) is msgs
    assert client.complete_calls == 0


def test_compact_noop_for_short_history():
    # Only system + 2 turns: too short to compact even if tokens were high.
    msgs = _msgs(1)
    client = _FakeClient()
    assert compact_history(msgs, client, object(), "m", context_window=16000) is msgs


def test_compact_summarizes_older_turns_and_keeps_recent_verbatim():
    msgs = _msgs(10)  # system + 20 turns, well over a small budget
    client = _FakeClient(summary="Papers discussed: A, B.")
    out = compact_history(msgs, client, object(), "m", context_window=2000, keep_recent=4)

    assert client.complete_calls == 1  # the summarizer ran exactly once
    assert out[0]["role"] == "system" and out[0]["content"] == "system"
    # A summary message was inserted.
    assert any(
        m["role"] == "system" and "Papers discussed" in m["content"]
        for m in out[1:]
    )
    # The last 4 messages are preserved verbatim (turns 8 and 9).
    recent = [m for m in out if m["role"] in {"user", "assistant"}]
    assert len(recent) == 4
    assert recent[-2]["content"].split()[0] == "9"   # user turn 9
    assert recent[-1]["content"].split()[0] == "a9"  # assistant turn 9
    assert total_tokens(out) < total_tokens(msgs)


def test_compact_never_starts_recent_with_a_tool_result():
    msgs = _msgs(10)
    # Inject a trailing assistant→tool pair so the boundary lands mid-sequence.
    msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "list_concepts", "arguments": "{}"}}]})
    msgs.append({"role": "tool", "tool_call_id": "t1", "content": "[]"})
    client = _FakeClient(summary="ok")
    out = compact_history(msgs, client, object(), "m", context_window=2000, keep_recent=4)
    # The tool result must be preceded by its assistant tool-call.
    idx_tool = next(i for i, m in enumerate(out) if m.get("role") == "tool")
    assert out[idx_tool - 1].get("tool_calls") is not None


def test_compact_drops_oldest_when_summarizer_fails():
    msgs = _msgs(10)
    client = _FakeClient(raise_on_complete=True)
    out = compact_history(msgs, client, object(), "m", context_window=2000, keep_recent=4)
    assert client.complete_calls == 1  # it tried to summarize
    # Fallback: system head + recent only, no summary message.
    assert out[0]["role"] == "system"
    assert all("Summary of earlier" not in (m.get("content") or "") for m in out)
    assert len(out) == 1 + 4  # head + keep_recent
    assert total_tokens(out) < total_tokens(msgs)
