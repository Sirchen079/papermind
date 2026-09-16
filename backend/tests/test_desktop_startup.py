"""Deterministic startup races, failed navigation and renderer hangs."""
import threading
from types import SimpleNamespace

import pytest

from app.desktop import open_workspace


def test_migrations_preserve_desktop_file_logging(env):
    import logging
    from app.desktop import configure_desktop_logs
    from app.main import create_app

    root = logging.getLogger()
    previous_handlers, previous_level = root.handlers[:], root.level
    try:
        path = configure_desktop_logs(env / 'desktop')
        handler = root.handlers[0]
        create_app()
        assert root.handlers == [handler]
        logging.info('desktop-after-migration')
        handler.flush()
        assert 'desktop-after-migration' in path.read_text(encoding='utf-8')
    finally:
        for handler in root.handlers:
            if handler not in previous_handlers:
                handler.close()
        root.handlers = previous_handlers
        root.setLevel(previous_level)


class Window:
    def __init__(self, outcomes=(True,)):
        self.events = SimpleNamespace(loaded=threading.Event())
        self.outcomes = outcomes
        self.calls = []

    def load_url(self, url):
        self.calls.append(url)
        if self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)] is not None:
            self.events.loaded.set()

    def evaluate_js(self, script):
        assert 'location.origin' in script and '#root > *' in script
        return self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]


def backend():
    return SimpleNamespace(url='http://127.0.0.1:4278', cancelled=threading.Event())


def test_fast_backend_does_not_navigate_before_slow_renderer():
    window, service = Window(), backend()
    waiting = threading.Event()

    class InitialDocument(threading.Event):
        def wait(self, timeout=None):
            waiting.set()
            return super().wait(timeout)

    window.events.loaded = InitialDocument()
    finished = []
    worker = threading.Thread(target=lambda: finished.append(open_workspace(window, service, timeout=1)))
    worker.start()
    try:
        assert waiting.wait(1), 'Startup must wait for the initial document'
        assert not window.calls
        window.events.loaded.set()
        worker.join(2)
        assert finished == [True]
        assert window.calls == [service.url]
    finally:
        service.cancelled.set()
        worker.join(2)


@pytest.mark.parametrize('first', [None, False])
def test_failed_navigation_or_blank_dom_retries_once(first):
    window, service = Window((first, True)), backend()
    window.events.loaded.set()
    assert open_workspace(window, service, timeout=.02)
    assert len(window.calls) == 2


def test_persistent_blank_page_is_reported():
    window, service = Window((False,)), backend()
    window.events.loaded.set()
    with pytest.raises(TimeoutError, match='已自动重试'):
        open_workspace(window, service, timeout=.01)
    assert len(window.calls) == 2


def test_uninitialized_renderer_is_reported_without_navigation():
    window = Window()
    with pytest.raises(TimeoutError, match='WebView2'):
        open_workspace(window, backend(), timeout=.01)
    assert not window.calls


def test_close_during_initialization_cancels_without_navigation():
    window, service = Window(), backend()
    service.cancelled.set()
    assert not open_workspace(window, service, timeout=.01)
    assert not window.calls


def test_renderer_script_hang_is_bounded():
    window, service = Window(), backend()
    release = threading.Event()
    window.evaluate_js = lambda _: release.wait(2)
    window.events.loaded.set()
    try:
        with pytest.raises(TimeoutError):
            open_workspace(window, service, timeout=.01, probe_timeout=.01)
        assert len(window.calls) == 2
    finally:
        release.set()
