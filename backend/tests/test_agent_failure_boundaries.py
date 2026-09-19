from types import SimpleNamespace

import pytest

from app.agent.loop import run_agent


@pytest.mark.parametrize('error', [RuntimeError('401 invalid API key'),
                                 RuntimeError('429 rate limit exceeded'),
                                 TimeoutError('connection timed out')])
def test_operational_failure_does_not_retry_without_library_tools(error):
    calls = []
    def complete(*args, **kwargs):
        calls.append(kwargs)
        raise error
    events = list(run_agent(SimpleNamespace(complete_with_tools=complete), None,
                            'synthetic', [{'role': 'user', 'content': 'question'}], None))
    assert len(calls) == 1
    assert [kind for kind, _ in events] == ['error']


def test_blank_final_answer_is_a_retryable_failure():
    turn = SimpleNamespace(content='  ', tool_calls=[], total_tokens=10)
    client = SimpleNamespace(complete_with_tools=lambda *a, **k: turn)
    events = list(run_agent(client, None, 'synthetic', [{'role': 'user', 'content': 'q'}], None))
    assert [kind for kind, _ in events] == ['error']


def test_step_exhaustion_is_not_saved_as_a_successful_answer():
    events = list(run_agent(None, None, 'synthetic', [], None, max_iters=0))
    assert [kind for kind, _ in events] == ['error']


def test_default_step_budget_is_100():
    """The default tool-step budget was raised from 8 (easily hit mid-research)."""
    calls = []
    turn = SimpleNamespace(content='', reasoning_content=None, total_tokens=1,
                           tool_calls=[SimpleNamespace(id='c', name='nonexistent_tool', arguments={})])

    def complete(*args, **kwargs):
        calls.append(1)
        return turn

    events = list(run_agent(SimpleNamespace(complete_with_tools=complete), None, 'synthetic',
                            [{'role': 'user', 'content': 'q'}], None))
    assert len(calls) == 100
    assert events[-1][0] == 'error'
    assert '步数上限' in events[-1][1]['message']
