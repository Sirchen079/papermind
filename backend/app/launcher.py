"""Entry point for the packaged PaperMind desktop app.

Starts the uvicorn server (which also serves the bundled frontend) and
opens the user's browser once the port is accepting connections.

Two ways to run:

* ``python -m app.launcher`` from the source tree (dev convenience).
* The frozen ``PaperMind.exe`` produced by PyInstaller (see build/).

Environment:

* ``PAPERMIND_PORT``        — override the listen port (default 4278).
* ``PAPERMIND_NO_BROWSER``  — set to any value to skip auto-opening the browser.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

# Must precede any transitive `import litellm` so startup does not depend on a
# remote model-cost-map fetch. Mirrors the guard in app/main.py.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import uvicorn  # noqa: E402

DEFAULT_PORT = 4278


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_then_open_browser(port: int, timeout: float = 15.0) -> None:
    """Poll the port, then launch the browser once the server answers."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_open(port):
            webbrowser.open(f"http://127.0.0.1:{port}")
            return
        time.sleep(0.25)
    # Server never came up; give up silently rather than spam the user.


def main() -> None:
    port = int(os.environ.get("PAPERMIND_PORT", DEFAULT_PORT))

    if not os.environ.get("PAPERMIND_NO_BROWSER"):
        # Daemon thread so it never blocks shutdown.
        threading.Thread(
            target=_wait_then_open_browser, args=(port,), daemon=True
        ).start()

    # Import lazily so the env-var guard above always wins, and so a failing
    # migration surfaces a clean traceback before uvicorn takes over logging.
    from app.main import create_app

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
