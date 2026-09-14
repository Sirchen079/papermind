import shutil
import socket
import subprocess
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


ROOT = Path(__file__).resolve().parents[2]


def run_start_script(port: int, *extra_args: str, dev: bool = True) -> subprocess.CompletedProcess[str]:
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "start.ps1"),
    ]
    if dev:
        args.append("-Dev")
    args.extend(["-Port", str(port), *extra_args])
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=35,
    )


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_start_script_reports_occupied_port_before_uvicorn_bind_error():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]

    try:
        result = run_start_script(port)
    finally:
        sock.close()

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert f"端口 {port} 已被占用" in output
    assert "换一个端口" in output


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_start_script_reuses_existing_papermind_before_dependency_checks():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path != "/api/health":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        result = run_start_script(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "PaperMind" in output
    assert str(port) in output


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_start_script_rebuild_refuses_to_reuse_running_papermind():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path != "/api/health":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        result = run_start_script(port, "-Rebuild", dev=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert f"PaperMind 已经在 http://127.0.0.1:{port} 运行" in output
    assert "-Rebuild 需要先关闭旧服务窗口" in output
