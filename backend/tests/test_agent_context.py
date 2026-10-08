"""Unit tests for context compaction (the user's explicit ask: summarize, don't truncate)."""
from app.agent.context import compact_history, total_tokens
from app.providers.client import CompletionResult


class _FakeClient:
    """Captures the summarizer call; controllable via ``summary`` / ``raise``."""

    def __init__(self, summary="folded summary", raise_on_complete=False):
        self._summary = summary
        self._raise = raise_on_complete
        self.complete_calls = 0
        self.messages = None

    def complete(self, provider, model_id, messages, request_kind, ref_id=None):  # noqa: ANN001
        self.complete_calls += 1
        self.messages = messages
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


def test_compaction_keeps_question_after_long_grounding():
    messages = _msgs(10)
    messages[1]['content'] = 'retrieved context ' * 500 + '[本轮用户问题]\nQUESTION_TO_KEEP'
    class Capture(_FakeClient):
        def complete(self, provider, model_id, messages, **kwargs):
            assert 'QUESTION_TO_KEEP' in messages[0]['content']
            return CompletionResult('summary',1,1,2)
    assert compact_history(messages, Capture(), object(), 'm', 2000)


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


def test_chinese_history_is_compacted_before_overflow_and_preserves_latest_question():
    msgs=[{'role':'system','content':'研究助手'}]
    for i in range(10):
        msgs.extend([{'role':'user','content':f'问题{i}：'+('研究资料条件'*60)},
                     {'role':'assistant','content':'相关结论需要核对。'*25}])
    client=_FakeClient(summary='前几轮讨论了资料适用条件。')
    result=compact_history(msgs,client,object(),'m',2000)
    assert client.complete_calls==1
    assert total_tokens(result)<=2000
    assert result[-2:]==msgs[-2:]


def test_one_oversized_current_turn_fails_without_losing_user_text_or_tool_results():
    import pytest
    messages=[{'role':'system','content':'助手'},{'role':'user','content':'最新问题'+('中文材料'*2000)}]
    with pytest.raises(ValueError,match='本轮问题和材料超出'):
        compact_history(messages,_FakeClient(),object(),'m',2000)
    assert messages[-1]['content'].startswith('最新问题')


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


def test_compaction_input_retains_late_correction_and_actual_save_receipt():
    import json
    messages = _msgs(35)
    messages[1]['content'] = 'RESEARCH_GOAL: compare noise robustness, not speed.'
    messages[-7]['content'] = '[本轮用户问题]\n' + 'Background. ' * 70 + 'CORRECTION: amplitude normalization is per receiver, not per experiment.'
    messages[-6] = {'role': 'assistant', 'content': '', 'tool_calls': [{
        'id': 'save17', 'type': 'function', 'function': {'name': 'save_document',
        'arguments': json.dumps({'filename': 'accepted-method.md', 'content': 'Corrected comparison.'})}}]}
    messages.insert(-5, {'role': 'tool', 'tool_call_id': 'save17',
                        'content': '{"ok":true,"filename":"accepted-method.md"}'})
    client = _FakeClient()
    compact_history(messages, client, object(), 'm', 4000, keep_recent=4)
    summary_input = client.messages[0]['content']
    assert 'RESEARCH_GOAL' in summary_input
    assert 'CORRECTION: amplitude normalization is per receiver' in summary_input
    assert 'save_document' in summary_input
    assert 'accepted-method.md' in summary_input
    assert 'save17' in summary_input
    assert '"ok":true' in summary_input
    assert total_tokens(client.messages) <= 3000


def test_summary_input_keeps_request_before_many_large_tool_results():
    from app.agent.context import _summary_transcript, estimate_tokens
    messages = [{'role': 'user', 'content': 'Initial goal'},
                {'role': 'user', 'content': 'LATEST_CORRECTION: preserve raw amplitude.'}]
    for i in range(20):
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': str(i), 'function': {'name': 'read_saved_document', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': str(i), 'content': '原文摘录' * 1000}])
    transcript = _summary_transcript(messages, 1500)
    assert 'Initial goal' in transcript and 'LATEST_CORRECTION' in transcript
    assert 'read_saved_document (19)' in transcript
    assert '已省略' in transcript
    assert estimate_tokens(transcript) <= 1500


def test_compaction_keeps_previous_summary_and_marks_large_record_omissions():
    from app.agent.context import _summary_transcript, estimate_tokens
    messages = [{'role': 'system', 'content': 'Earlier goal and accepted choices'},
                {'role': 'user', 'content': 'START_REQUIREMENT ' + 'long material ' * 1000 + ' END_CORRECTION'}]
    for budget in (128, 1000, 6000):
        transcript = _summary_transcript(messages, budget)
        assert 'START_REQUIREMENT' in transcript and 'END_CORRECTION' in transcript
        assert estimate_tokens(transcript) <= budget


def test_small_summary_input_budget_accounts_for_chinese_and_omission_markers():
    from app.agent.context import _summary_transcript, estimate_tokens
    messages = [{'role': 'user', 'content': '原始目标' * 200},
                {'role': 'assistant', 'content': '旧稿' * 400},
                {'role': 'user', 'content': '最新更正' * 300}]
    for budget in (128, 200, 500, 1000):
        transcript = _summary_transcript(messages, budget)
        assert '最新更正' in transcript
        assert estimate_tokens(transcript) <= budget


def test_oversized_generated_summary_keeps_marked_context_instead_of_discarding_it():
    messages = _msgs(10)
    client = _FakeClient(summary='Goal and decisions. ' + 'Repeated background. ' * 2000 + ' Latest correction.')
    result = compact_history(messages, client, object(), 'm', 2000, keep_recent=4)
    assert result[-4:] == messages[-4:]
    assert result[1]['role'] == 'system'
    assert 'Goal and decisions.' in result[1]['content']
    assert 'Latest correction.' in result[1]['content']
    assert '中间内容已省略' in result[1]['content']
    assert total_tokens(result) <= 1500
    assert client.complete_calls == 1


def _long_reading_span(rounds=8, body_size=1600):
    messages = [{'role': 'system', 'content': 'Research assistant'},
                {'role': 'user', 'content': 'Compare selected papers; preserve amplitude conditions.'}]
    for index in range(rounds):
        messages.extend([
            {'role': 'assistant', 'content': f'Read paper {index}', 'tool_calls': [
                {'id': f'read{index}', 'type': 'function', 'function': {
                    'name': 'get_paper_full_text', 'arguments': '{"paper_id":' + str(index) + '}'}}]},
            {'role': 'tool', 'tool_call_id': f'read{index}', 'content': f'P{index}: ' + 'x' * body_size}])
    return messages


def test_one_long_reading_task_compacts_completed_batches_and_keeps_user_request():
    import copy
    messages = _long_reading_span()
    original = copy.deepcopy(messages)
    client = _FakeClient('Read papers 0 through 5; compare conditions next.')
    result = compact_history(messages, client, object(), 'm', 2000)
    assert client.complete_calls == 1
    assert total_tokens(result) <= 1500
    assert messages == original
    assert messages[1] in result
    assert result[-2:] == messages[-2:]
    assert 'get_paper_full_text' in client.messages[0]['content']
    for index, message in enumerate(result):
        if message.get('role') == 'tool':
            assert any(call['id'] == message['tool_call_id'] for prior in result[:index] for call in prior.get('tool_calls', []))


def test_split_span_keeps_multiple_tool_results_together():
    messages = _long_reading_span()
    batch = [{'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': name, 'type': 'function', 'function': {'name': 'read_saved_document', 'arguments': '{}'}}
        for name in ('a', 'b')]},
        {'role': 'tool', 'tool_call_id': 'b', 'content': 'Second result'},
        {'role': 'tool', 'tool_call_id': 'a', 'content': 'First result'}]
    messages.extend(batch)
    result = compact_history(messages, _FakeClient(), None, 'm', 2000)
    assert result[-3:] == batch
    assert messages[1] in result


def test_single_large_tool_response_can_be_summarized_without_shortening_question():
    messages = _long_reading_span(rounds=1, body_size=16000)
    client = _FakeClient('P0 read; source can be reopened by paper id.')
    result = compact_history(messages, client, None, 'm', 2000)
    assert result[-1] == messages[1]
    assert result[1]['content'].endswith('P0 read; source can be reopened by paper id.')
    assert 'read0' in client.messages[0]['content']
    assert total_tokens(result) <= 1500


def test_repeated_in_task_compaction_retains_prior_summary_and_original_request():
    client = _FakeClient('PRIOR_FINDING: P0 supports only synthetic data.')
    original = _long_reading_span()
    first = compact_history(original, client, None, 'm', 2000)
    more = _long_reading_span(rounds=4)[2:]
    second = compact_history([*first, *more], client, None, 'm', 2000)
    assert original[1] in second
    assert 'PRIOR_FINDING' in client.messages[0]['content']
    assert total_tokens(second) <= 1500


def test_in_task_summary_failure_preserves_marked_records_and_recent_tools():
    messages = _long_reading_span()
    result = compact_history(messages, _FakeClient(raise_on_complete=True), None, 'm', 2000)
    assert result[-2:] == messages[-2:]
    assert messages[1] in result
    assert result[1]['content'].startswith('Earlier tool records (summary unavailable)')
    assert 'get_paper_full_text' in result[1]['content']
    assert total_tokens(result) <= 1500


def test_agent_continues_after_large_reads_without_reexecuting_tools(monkeypatch):
    import json
    from types import SimpleNamespace
    from app.agent.loop import run_agent
    from app.providers.client import ToolCall, ToolTurn
    calls = []
    def read_part(part):
        calls.append(part)
        return json.dumps({'part': part, 'content': 'paper excerpt ' * 1000})
    monkeypatch.setattr('app.agent.loop.get_tool', lambda name: SimpleNamespace(
        parameters={'properties': {'part': {}}}, run=lambda session, **args: read_part(**args)))
    class ReadingClient(_FakeClient):
        steps = 0
        def complete_with_tools(self, provider, model, messages, *args, **kwargs):
            assert total_tokens(messages) <= 1500
            assert original[1] in messages
            self.steps += 1
            if self.steps <= 3:
                return ToolTurn('', [ToolCall(str(self.steps), 'read_test_part', {'part': self.steps})], 1, 1, 2)
            return ToolTurn('Comparison ready.', [], 1, 1, 2)
    original = _long_reading_span(rounds=0)
    client = ReadingClient('Previously read parts; continue comparison.')
    events = list(run_agent(client, None, 'm', original, None, context_window=2000, max_iters=5))
    assert any(kind == 'done' and data['content'] == 'Comparison ready.' for kind, data in events)
    assert calls == [1, 2, 3]
    assert client.complete_calls == 3
    assert next(data['tokens'] for kind, data in events if kind == 'done') == 14
    assert any(kind == 'status' and data.get('context', {}).get('compacted') for kind, data in events)
