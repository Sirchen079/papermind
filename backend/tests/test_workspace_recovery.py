import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.db.engine import get_engine
from app.main import create_app
from app.workspaces.context import bind_workspace


def create(client, name):
    response = client.post('/api/workspaces', json={'name': name})
    assert response.status_code == 201, response.text
    return response.json()['id']


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
def test_one_unavailable_workspace_preserves_other_projects_and_can_be_restored(client, legacy, damage):
    broken = 'legacy' if legacy else create(client, 'Recovery test')
    healthy = create(client, 'Healthy research')
    bad_url = f'/api/w/{broken}/papers'
    good_url = f'/api/w/{healthy}/papers'
    assert client.post(bad_url + '/manual', json={'title': 'Keep original evidence'}).status_code == 201
    assert client.post(good_url + '/manual', json={'title': 'Healthy evidence'}).status_code == 201
    context = client.app.state.workspaces.context(broken)
    # A real offline backup, with the original application's WAL checkpointed.
    snapshot = context.db_path.with_suffix('.snapshot')
    with closing(sqlite3.connect(context.db_path)) as source, closing(sqlite3.connect(snapshot)) as backup:
        source.backup(backup)
        source.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    with bind_workspace(context):
        get_engine().dispose()
    if damage == 'missing':
        context.db_path.rename(context.db_path.with_suffix('.offline'))
    else:
        context.db_path.write_bytes(b'corrupt synthetic fixture')

    restarted = TestClient(create_app())
    assert restarted.get('/api/health').status_code == 200
    assert restarted.get(bad_url).status_code == 503
    if legacy:
        assert restarted.get('/api/papers').status_code == 503
    if damage == 'missing':
        assert not context.db_path.exists(), 'startup or a read silently replaced the missing project'
    else:
        assert context.db_path.read_bytes() == b'corrupt synthetic fixture'
    rows = restarted.get('/api/workspaces').json()
    assert next(w for w in rows if w['id'] == broken)['available'] is False
    assert next(w for w in rows if w['id'] == healthy)['available'] is True
    assert restarted.get(good_url).json()['items'][0]['title'] == 'Healthy evidence'
    create(restarted, 'Created while another project is unavailable')

    context.db_path.write_bytes(snapshot.read_bytes())
    restored = TestClient(create_app())
    assert restored.get(bad_url).json()['items'][0]['title'] == 'Keep original evidence'
    assert restored.get(good_url).json()['items'][0]['title'] == 'Healthy evidence'


def test_missing_database_is_rejected_even_before_restart(client):
    wid = create(client, 'Detached disk')
    context = client.app.state.workspaces.context(wid)
    with bind_workspace(context):
        get_engine().dispose()
    context.db_path.rename(context.db_path.with_suffix('.offline'))
    assert client.get(f'/api/w/{wid}/papers').status_code == 503
    assert not context.db_path.exists()


def test_failed_initial_migration_does_not_hide_healthy_projects(client, monkeypatch):
    broken = create(client, 'Failed migration')
    healthy = create(client, 'Healthy')
    from app.workspaces.context import current_workspace
    from app import main
    original = main._run_migrations
    def upgrade():
        if current_workspace.get().id == broken:
            raise RuntimeError('Synthetic disk write failure')
        original()
    monkeypatch.setattr(main, '_run_migrations', upgrade)
    restarted = TestClient(create_app())
    assert restarted.get(f'/api/w/{broken}/papers').status_code == 503
    assert restarted.get(f'/api/w/{healthy}/papers').status_code == 200
