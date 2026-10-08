"""Best-effort discovery file so external local tools can find this backend.

The desktop app normally binds 127.0.0.1:4278 but silently falls back to a
random free port when it is taken, and a headless run may override
``PAPERMIND_PORT``. External AI CLI tools need one stable place to look up the
actual port. ``<data dir>/agent_access.json`` is written next to the existing
``api_token`` whenever the server binds, and carries the port, PID and start
time. It is advisory only: readers confirm liveness via ``GET /api/health``
and never treat a stale file as authoritative.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)
FILENAME = 'agent_access.json'


def write_access_file(port: int) -> None:
    path = _path()
    if path is None:
        return
    payload = {
        'api': f'http://127.0.0.1:{int(port)}',
        'port': int(port),
        'pid': os.getpid(),
        'started_at': datetime.now(timezone.utc).isoformat(),
        'token_file': 'api_token',
        'health': '/api/health',
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)
    except OSError:
        # Discovery is a convenience; never block server startup over it.
        _log.warning('Could not write agent access file', exc_info=True)


def _path() -> Path | None:
    try:
        from app.paths import default_data_dir

        return default_data_dir() / FILENAME
    except Exception:  # pragma: no cover - paths import must not raise in practice
        return None
