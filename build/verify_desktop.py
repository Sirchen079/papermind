"""Verify the actual frozen desktop, including WebView2 and React, in isolation."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def verify(executable: Path, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    log = data_dir / "desktop/desktop.log"
    offset = log.stat().st_size if log.exists() else 0
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PAPERMIND_") and k not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update(PAPERMIND_DATA_DIR=str(data_dir.resolve()), PAPERMIND_PORT="0")
    process = subprocess.Popen([str(executable.resolve()), "--desktop-smoke-test"], env=env)
    try:
        code = process.wait(timeout=150)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise RuntimeError(f"Desktop verification timed out; inspect {log}")
    text = log.read_bytes()[offset:].decode("utf-8") if log.exists() else ""
    if code != 0 or "Desktop workspace rendered" not in text or "ERROR" in text:
        raise RuntimeError(f"Desktop verification failed (exit {code}):\n{text}")
    print(f"PASS: native desktop + WebView2 + React + normal exit: {executable}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    # Keep diagnostics if verification fails; never touch the user's library.
    directory = Path(tempfile.mkdtemp(prefix="papermind-desktop-check-"))
    print(f"Verification data: {directory}", flush=True)
    verify(args.executable, directory)
    verify(args.executable, directory)
