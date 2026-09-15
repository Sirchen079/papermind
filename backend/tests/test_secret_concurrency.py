from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest


@pytest.mark.parametrize('kind', ['master-key', 'local-token'])
def test_first_use_returns_one_durable_secret_to_concurrent_callers(tmp_path, monkeypatch, kind):
    from app.security import master_key, local_token
    if kind == 'master-key':
        path = tmp_path / 'new.key'
        original = master_key.Fernet.generate_key
        owner, name = master_key.Fernet, 'generate_key'
        read = lambda: master_key.load_or_create_master_key(path)
    else:
        path = tmp_path / 'api_token'
        monkeypatch.setattr(local_token, '_token_path', lambda: path)
        original = local_token.secrets.token_urlsafe
        owner, name = local_token.secrets, 'token_urlsafe'
        read = local_token.get_or_create_token
    entered = Event()

    def slow_generate(*args):
        entered.set()
        time.sleep(0.15)  # Widen first-use creation, not an ordering assertion.
        return original(*args)

    monkeypatch.setattr(owner, name, slow_generate)
    with ThreadPoolExecutor(max_workers=8) as pool:
        first = pool.submit(read)
        assert entered.wait(5)
        rest = [pool.submit(read) for _ in range(7)]
        values = [first.result(), *(future.result() for future in rest)]
    assert len(set(values)) == 1
    stored = path.read_bytes() if kind == 'master-key' else path.read_text().strip()
    assert values[0] == stored


def test_token_authorization_cache_follows_the_application_directory(tmp_path, monkeypatch):
    from app.security import local_token
    local_token.reset_token_cache()
    monkeypatch.setenv('PAPERMIND_DATA_DIR', str(tmp_path / 'one'))
    one = local_token.get_or_create_token()
    assert local_token.require_local_token(one) == one
    monkeypatch.setenv('PAPERMIND_DATA_DIR', str(tmp_path / 'two'))
    two = local_token.get_or_create_token()
    assert two != one
    assert local_token.require_local_token(two) == two
    local_token.reset_token_cache()


def test_missing_local_key_does_not_replace_credentials_with_a_new_key(client):
    from app.config import get_settings
    from app.security.crypto import _build_crypto
    from pathlib import Path
    client.post('/api/providers', json={'name':'Existing secret','type':'openai_chat','api_key':'synthetic-local'})
    path = Path(get_settings().resolved_master_key_path)
    path.unlink()
    _build_crypto.cache_clear()  # A restart or cache eviction used to create a different key.
    response = client.post('/api/providers', json={'name':'New provider','type':'openai_chat','api_key':'synthetic-new'})
    assert response.status_code == 409
    assert not path.exists()


def test_missing_shared_key_does_not_get_recreated_during_attach(client):
    from app.providers import shared
    from app.security.crypto import _build_crypto
    pid = client.post('/api/providers', json={'name':'Shared secret','type':'openai_chat','api_key':'synthetic-shared'}).json()['id']
    published = client.post(f'/api/providers/{pid}/share').json()['id']
    wid = client.post('/api/workspaces', json={'name':'Attach target'}).json()['id']
    path = shared.application_dir() / 'connections.key'
    path.unlink()
    _build_crypto.cache_clear()
    # Before the fix this surfaced an InvalidToken server error and left a new key.
    from fastapi.testclient import TestClient
    result = TestClient(client.app, raise_server_exceptions=False).post(f'/api/w/{wid}/providers/attach', json={'connection_id':published})
    assert result.status_code == 409
    assert not path.exists()
