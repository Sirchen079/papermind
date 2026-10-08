"""Shared visible-text and reasoning allowances within a model's context.

The existing review budget also applies to short structured tasks: their JSON
may be short, but configured reasoning consumes the same output allowance.
"""


def text_budget(window, output):
    return min(output, max(128, window // 3))


def response_budget(window, output, effort=None, reasoning_budget=None):
    text = text_budget(window, output)
    reserve = ({'medium': 4096, 'high': 8192, 'xhigh': 16384, 'max': 16384}.get(effort, 0)
               if reasoning_budget is None else reasoning_budget)
    return text + min(reserve, max(0, window // 2 - text))
