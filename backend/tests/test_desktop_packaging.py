from pathlib import Path

import pytest

from app.desktop import main, startup_error_message


def test_missing_dependency_reports_package_failure():
    message = startup_error_message(ModuleNotFoundError("No module named 'proxy_tools'"), Path("desktop.log"))
    assert "安装包" in message
    assert "proxy_tools" in message
    assert "WebView2" not in message


def test_other_startup_failure_preserves_actual_error():
    message = startup_error_message(PermissionError("Access denied"), Path("desktop.log"))
    assert "PermissionError: Access denied" in message
    assert "desktop.log" in message
    assert "请确认已安装" not in message


def test_smoke_test_cannot_use_default_user_library(monkeypatch):
    monkeypatch.delenv("PAPERMIND_DATA_DIR", raising=False)
    with pytest.raises(ValueError, match="isolated"):
        main(smoke_test=True)
