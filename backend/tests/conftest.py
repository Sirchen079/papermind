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
    # Keep bundled user_skills/ out of the test DB so skill-count assertions
    # stay deterministic (create_app auto-loads them in production otherwise).
    monkeypatch.setenv("PAPERMIND_NO_AUTOLOAD_SKILLS", "1")
    return tmp_path


@pytest.fixture
def client(env):
    from app.main import create_app
    return TestClient(create_app())


@pytest.fixture
def accept_evidence_review(monkeypatch):
    """Transport stub for tests of chat persistence, not semantic review.

    The verifier has separate failure/edit tests and real-provider acceptance.
    Other request kinds still use the test's original provider mock.
    """
    from types import SimpleNamespace
    from app.providers.client import ProviderClient
    original=ProviderClient.complete
    def complete(self,*args,**kwargs):
        if kwargs.get('request_kind')=='evidence_review':
            return SimpleNamespace(content='{"edits":[]}',total_tokens=2)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(ProviderClient,'complete',complete)
