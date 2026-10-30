from pathlib import Path

import pytest
from app.ingestion import institutional_runtime as runtime


def test_install_failure_reports_tls_without_leaking_raw_output(monkeypatch):
    def fail(*args, **kwargs):
        raise runtime.subprocess.CalledProcessError(1, ['uv'], stderr='SECRET tls handshake eof')
    monkeypatch.setattr(runtime.subprocess, 'run', fail)
    with pytest.raises(runtime.PreparationError, match='TLS') as error:
        runtime._run(['uv', 'pip', 'install'])
    assert 'SECRET' not in str(error.value)


def test_prepare_pins_engine_isolates_browser_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPERMIND_INSTITUTION_RUNTIME', str(tmp_path))
    monkeypatch.setenv('PYTHONHOME', 'parent-frozen-runtime')
    monkeypatch.setattr(runtime, '_uv', lambda: 'uv')
    calls = []
    def run(argv):
        calls.append(argv)
        python = runtime.python_path()
        python.parent.mkdir(parents=True, exist_ok=True)
        python.touch()
    monkeypatch.setattr(runtime, '_run', run)
    runtime.prepare()
    runtime.prepare()
    assert len(calls) == 3
    assert runtime.REVISION in ' '.join(calls[1])
    assert 'cloakbrowser==0.3.31' in calls[1]
    assert runtime.ready()
    assert runtime.environment()['CLOAKBROWSER_CACHE_DIR'] == str(tmp_path / 'browser')
    assert 'PYTHONHOME' not in runtime.environment()


def test_failed_install_never_marks_environment_ready(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPERMIND_INSTITUTION_RUNTIME', str(tmp_path))
    monkeypatch.setattr(runtime, '_uv', lambda: 'uv')
    def fail(argv):
        raise OSError('offline')
    monkeypatch.setattr(runtime, '_run', fail)
    with pytest.raises(OSError):
        runtime.prepare()
    assert not runtime.ready()
    assert runtime._install_lock.acquire(blocking=False)
    runtime._install_lock.release()


def test_corrupt_uv_archive_is_not_executed(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPERMIND_INSTITUTION_RUNTIME', str(tmp_path))
    monkeypatch.setattr(runtime.shutil, 'which', lambda _: None)
    import httpx
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b'corrupt executable'))
    original = httpx.Client
    monkeypatch.setattr(runtime.httpx, 'Client', lambda **kw: original(transport=transport))
    with pytest.raises(ValueError, match='校验失败'):
        runtime._uv()
    assert not (tmp_path / 'tools' / 'uv.exe').exists()
