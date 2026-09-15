"""The research agent — a tool-calling harness, not a single completion call.

Instead of one frozen-context answer, the assistant runs a loop: it can call
tools to investigate the library (search, read a paper, list concepts, find
related work), see the results, and keep going until it can answer. Long
conversations are kept inside the model's context window by compacting older
turns into a running summary (see ``context.compact_history``).
"""
