import os
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so `import app` works without install.
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Avoid litellm's remote model-cost-map fetch on import (network dep + latency).
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("PAPERMIND_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PAPERMIND_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("PAPERMIND_MASTER_KEY_PATH", str(tmp_path / "master.key"))
    return tmp_path


@pytest.fixture
def client(env):
    from app.main import create_app
    return TestClient(create_app())
