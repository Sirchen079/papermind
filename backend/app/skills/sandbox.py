"""Sandboxed execution for tool-type (C-type) skills.

A tool skill's body is Python code. We run it in an **isolated subprocess** so a
crash, infinite loop, or excessive memory use in the skill cannot take down the
FastAPI process. Isolation measures:

  * separate process (the app is unaffected by skill crashes/segfaults);
  * a fresh temporary working directory (the skill starts in an empty folder);
  * a wall-clock timeout (kills hangs);
  * a curated environment (env vars whose name looks like a secret — KEY / SECRET
    / TOKEN / PASSWORD / CREDENTIAL — are stripped before the skill sees them).

.. note::
   This is **process isolation**, not a hardened security sandbox. It suits a
   local single-user app where the user authors their own skills; it will NOT
   stop a malicious author (the code can still open absolute paths or reach the
   network). For that, run under an OS-level jail (container / Job Object /
   seccomp) — out of scope for the single-user desktop case.

The library context is pre-loaded into magic globals (``library``, ``papers``,
``paper``, ``user_input``) so a skill can start working immediately; anything the
skill ``print()``s becomes its result.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 10.0

# Prepended to every skill so its body can use library context directly.
_BOOTSTRAP = (
    "import json as _json, os as _os\n"
    "_ctx = _json.load(open(_os.environ['PAPERMIND_CONTEXT_FILE'], encoding='utf-8'))\n"
    "library = _ctx.get('library', {})\n"
    "papers = _ctx.get('papers', [])\n"
    "paper = _ctx.get('paper')\n"
    "user_input = _ctx.get('input', '')\n"
)

_SENSITIVE = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")


@dataclass
class ToolResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


def _sandbox_env(extra: dict[str, str]) -> dict[str, str]:
    """Copy the parent env minus anything that looks like a secret, then add extras."""
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in _SENSITIVE)}
    env.update(extra)
    return env


def run_tool(
    code: str, context: dict | None = None, timeout: float = DEFAULT_TIMEOUT
) -> ToolResult:
    """Execute ``code`` in an isolated subprocess; return captured output.

    ``context`` is JSON-serialized to a temp file whose path is exposed to the
    skill via the ``PAPERMIND_CONTEXT_FILE`` env var (and pre-loaded into
    ``library``/``papers``/``paper``/``user_input`` globals by the bootstrap).
    """
    context = context or {}
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="papermind-skill-") as workdir:
        work = Path(workdir)
        (work / "context.json").write_text(
            json.dumps(context, ensure_ascii=False), encoding="utf-8"
        )
        script = work / "_skill.py"
        script.write_text(_BOOTSTRAP + "\n" + code, encoding="utf-8")
        env = _sandbox_env({"PAPERMIND_CONTEXT_FILE": str(work / "context.json")})
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ToolResult(
                ok=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout if isinstance(exc.stdout, str) else ""
            return ToolResult(
                ok=False,
                stdout=out,
                stderr=f"timed out after {timeout}s",
                exit_code=-1,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
