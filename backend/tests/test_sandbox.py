import os

from app.skills.sandbox import run_tool


def test_run_tool_captures_stdout():
    res = run_tool("print('hello skill')")
    assert res.ok is True
    assert res.exit_code == 0
    assert "hello skill" in res.stdout


def test_run_tool_loads_context_globals():
    # `library` / `papers` / `user_input` are pre-loaded from the context file.
    res = run_tool(
        "print(library['papers'], len(papers), user_input)",
        context={"library": {"papers": 3}, "papers": [{}, {}], "input": "hi"},
    )
    assert res.ok, res.stderr
    assert "3 2 hi" in res.stdout


def test_run_tool_reports_nonzero_exit():
    res = run_tool("import sys; print('boom', file=sys.stderr); sys.exit(3)")
    assert res.ok is False
    assert res.exit_code == 3
    assert "boom" in res.stderr


def test_run_tool_enforces_timeout():
    res = run_tool("import time; time.sleep(5)", timeout=1.0)
    assert res.ok is False
    assert res.exit_code == -1
    assert "timed out" in res.stderr


def test_run_tool_strips_secret_env(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "supersecret")
    monkeypatch.setenv("HARMLESS_VAR", "kept")
    res = run_tool("import os; print(os.environ.get('MY_API_KEY', 'none'), os.environ.get('HARMLESS_VAR', 'none'))")
    assert res.ok, res.stderr
    assert "none" in res.stdout  # secret stripped
    assert "kept" in res.stdout  # harmless env preserved


def test_run_tool_uses_isolated_cwd():
    # The skill's working directory is a fresh temp dir, not the app's cwd.
    res = run_tool("import os; print(os.getcwd())")
    assert res.ok, res.stderr
    assert os.path.abspath(res.stdout.strip()) != os.path.abspath(os.getcwd())
    assert "papermind-skill-" in res.stdout


def test_run_tool_syntax_error_is_captured_not_raised():
    res = run_tool("def broken(:")  # invalid Python
    assert res.ok is False
    assert res.exit_code != 0
    assert res.stderr.strip() != ""
