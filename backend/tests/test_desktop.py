import socket
import sys
import time

import pytest

from app.desktop import InstanceLock, LocalBackend, loading_page, reserve_socket


def test_reserved_port_is_owned_and_conflict_gets_independent_port():
    with reserve_socket(0) as first:
        first_port = first.getsockname()[1]
        with reserve_socket(first_port) as second:
            assert second.getsockname()[0] == "127.0.0.1"
            assert second.getsockname()[1] != first_port
        with pytest.raises(OSError):
            reserve_socket(first_port, fallback=False)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop instance lock")
def test_instance_lock_prevents_duplicates_and_releases(tmp_path, monkeypatch):
    activated = []
    monkeypatch.setattr("app.desktop.activate_process", activated.append)
    first = InstanceLock(tmp_path / "desktop.lock")
    second = InstanceLock(tmp_path / "desktop.lock")
    third = InstanceLock(tmp_path / "other-library.lock")
    try:
        assert first.acquire()
        assert not second.acquire()
        assert len(activated) == 1
        assert third.acquire(), "Independent test libraries must not share the lock"
        first.close()
        assert second.acquire()
    finally:
        first.close()
        second.close()
        third.close()


def test_backend_lifecycle_starts_and_stops_without_an_external_browser(monkeypatch):
    from fastapi import FastAPI
    monkeypatch.setattr("app.main.create_app", lambda: FastAPI())
    server = LocalBackend(reserve_socket(0))
    port = server.sock.getsockname()[1]
    try:
        server.start()
        assert server.wait_ready(timeout=5)
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    finally:
        server.stop()
    assert not server.thread.is_alive()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=.2)


def test_failed_backend_and_cancelled_startup_do_not_hang(monkeypatch):
    def fail():
        raise RuntimeError("synthetic migration error")
    monkeypatch.setattr("app.main.create_app", fail)
    server = LocalBackend(reserve_socket(0))
    try:
        server.start()
        with pytest.raises(RuntimeError):
            server.wait_ready(timeout=3)
    finally:
        server.stop()
    cancelled = LocalBackend(reserve_socket(0))
    cancelled.cancelled.set()
    assert not cancelled.wait_ready(timeout=.1)
    cancelled.stop()


def test_loading_error_page_escapes_paths_and_messages():
    page = loading_page("<script>bad</script>", error=True)
    assert "<script>bad</script>" not in page
    assert "&lt;script&gt;" in page
