from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session

from app.archive import application
from app.db.engine import get_engine
from app.models import Paper
from app.workspaces.context import bind_workspace


@pytest.fixture(autouse=True)
def fresh_local_token(env):
    from app.security.local_token import reset_token_cache
    reset_token_cache()
    yield
    reset_token_cache()


def seed(client):
    registry = client.app.state.workspaces
    wid = client.post('/api/workspaces', json={'name': 'Archive project B', 'goal': 'Independent goal'}).json()['id']
    provider = client.post('/api/providers', json={
        'name': 'Shared synthetic', 'type': 'openai_chat', 'api_key': 'synthetic-shared-key',
    }).json()
    client.post(f"/api/providers/{provider['id']}/models", json={'model_id': 'synthetic', 'role_default': 'chat'})
    shared = client.post(f"/api/providers/{provider['id']}/share").json()
    assert client.post('/api/w/' + wid + '/providers/attach', json={'connection_id': shared['id']}).status_code == 201
    for project_id, title in [('legacy', 'Legacy private'), (wid, 'B private')]:
        scope = registry.context(project_id)
        pdfs = scope.data_dir / 'pdfs'
        pdfs.mkdir(exist_ok=True)
        path = pdfs / 'same.pdf'
        path.write_bytes(b'%PDF-1.4 ' + title.encode())
        with bind_workspace(scope), Session(get_engine()) as session:
            session.add(Paper(source='manual', title=title, pdf_path=str(path.resolve())))
            session.commit()
    return wid, shared['id']


def backup(client, request_id=None):
    response = client.post('/api/workspaces/backups', json={'request_id': request_id or str(uuid4())})
    assert response.status_code == 201, response.text
    registry = client.app.state.workspaces
    return application.resolve_backup(registry, response.json()['filename'])


def test_whole_backup_restores_directory_shared_connections_and_custom_legacy_paths(client, env, monkeypatch):
    from app.main import create_app
    from app.providers.selection import pick_llm
    wid, shared_id = seed(client)
    assert client.app.state.workspaces.legacy.db_path.parent != client.app.state.workspaces.root
    assert client.patch('/api/workspaces/' + wid, json={'archived': True}).status_code == 200
    archive_path = backup(client)
    verified = application.verify(archive_path)
    assert verified['ok'], verified
    assert {row['id'] for row in verified['projects']} == {'legacy', wid}
    restored = env / 'restored'
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(restored)  # Own generated, fully verified fixture archive.
    data_root = restored / 'application'
    monkeypatch.setenv('PAPERMIND_DATA_DIR', str(data_root))
    monkeypatch.delenv('PAPERMIND_DB_PATH')
    monkeypatch.delenv('PAPERMIND_MASTER_KEY_PATH')
    restarted = TestClient(create_app())
    rows = restarted.get('/api/workspaces').json()
    assert all(row['available'] for row in rows)
    assert next(row for row in rows if row['id'] == wid)['archived']
    for project_id, title in [('legacy', 'Legacy private'), (wid, 'B private')]:
        prefix = '/api/w/' + project_id
        paper = restarted.get(prefix + '/papers').json()['items'][0]
        assert paper['title'] == title
        assert (restarted.app.state.workspaces.context(project_id).data_dir / 'pdfs' / 'same.pdf').read_bytes().endswith(title.encode())
        with bind_workspace(restarted.app.state.workspaces.context(project_id)), Session(get_engine()) as session:
            llm, provider, model = pick_llm(session, 'chat')
            assert llm._api_key(provider) == 'synthetic-shared-key'
            assert model == 'synthetic'
        with closing(sqlite3.connect(restarted.app.state.workspaces.context(project_id).db_path)) as db:
            assert db.execute('SELECT pdf_path FROM paper').fetchone()[0] == 'same.pdf'
            assert db.execute('SELECT shared_connection_id FROM provider').fetchone()[0] == shared_id


def test_backup_retry_is_idempotent_and_missing_pdf_failure_is_recoverable(client):
    wid, _ = seed(client)
    scope = client.app.state.workspaces.context(wid)
    path = scope.data_dir / 'pdfs' / 'same.pdf'
    content = path.read_bytes()
    path.unlink()
    request_id = str(uuid4())
    failed = client.post('/api/workspaces/backups', json={'request_id': request_id})
    assert failed.status_code == 409 and '原文文件' in failed.text
    assert client.get('/api/workspaces/backups').json() == []
    path.write_bytes(content)
    first = backup(client, request_id)
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    second = backup(client, request_id)
    assert first == second and hashlib.sha256(second.read_bytes()).hexdigest() == digest
    assert len(client.get('/api/workspaces/backups').json()) == 1


@pytest.mark.parametrize('mutation', ['missing-key', 'traversal', 'extra', 'broken-db', 'bad-hash', 'false-directory'])
def test_verifier_rejects_incomplete_or_modified_application_archives(client, env, mutation):
    seed(client)
    original = backup(client)
    with zipfile.ZipFile(original) as archive:
        content = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(content['manifest.json'])
    if mutation == 'missing-key':
        content.pop('application/connections.key')
        manifest['files'] = [row for row in manifest['files'] if row['path'] != 'application/connections.key']
    elif mutation == 'traversal':
        name = 'application/pdfs/../../escaped.txt'
        content[name] = b'bad'
        manifest['files'].append({'path': name, 'size_bytes': 3, 'sha256': hashlib.sha256(b'bad').hexdigest()})
    elif mutation == 'extra':
        content['application/pdfs/extra.pdf'] = b'extra'
    elif mutation == 'broken-db':
        name = 'application/papermind.sqlite'
        content[name] = b'SQLite format 3\x00' + b'broken'
        row = next(row for row in manifest['files'] if row['path'] == name)
        row.update(size_bytes=len(content[name]), sha256=hashlib.sha256(content[name]).hexdigest())
    elif mutation == 'bad-hash':
        manifest['files'][0]['sha256'] = '0' * 64
    elif mutation == 'false-directory':
        manifest['projects'][0]['name'] = 'Not the recorded project name'
    content['manifest.json'] = json.dumps(manifest).encode()
    tampered = env / 'tampered.zip'
    with zipfile.ZipFile(tampered, 'w') as archive:
        for name, data in content.items():
            archive.writestr(name, data)
    verified = application.verify(tampered)
    assert not verified['ok'] and verified['errors']
    assert not (env / 'escaped.txt').exists()


def test_application_download_requires_local_token_and_invalid_names_are_rejected(client):
    seed(client)
    path = backup(client)
    assert client.get('/api/workspaces/backups/' + path.name).status_code == 403
    from app.security.local_token import get_or_create_token
    response = client.get('/api/workspaces/backups/' + path.name, headers={'X-Local-Token': get_or_create_token()})
    assert response.status_code == 200 and response.content == path.read_bytes()
    assert client.get('/api/workspaces/backups/other.zip', headers={'X-Local-Token': get_or_create_token()}).status_code == 404
    assert client.post('/api/workspaces/backups/' + path.name + '/verify').json()['ok']


def test_native_download_ticket_is_protected_single_use_and_expiring(client):
    seed(client)
    path = backup(client)
    endpoint = '/api/workspaces/backups/' + path.name + '/download-ticket'
    assert client.post(endpoint).status_code == 403
    from app.security.local_token import get_or_create_token
    headers = {'X-Local-Token': get_or_create_token()}
    url = client.post(endpoint, headers=headers).json()['url']
    assert client.get(url).content == path.read_bytes()
    assert client.get(url).status_code == 404
    url = client.post(endpoint, headers=headers).json()['url']
    token = url.rsplit('/', 1)[-1]
    saved, _ = client.app.state.application_downloads[token]
    client.app.state.application_downloads[token] = (saved, -1)
    assert client.get(url).status_code == 404


def test_restore_guide_uses_actual_custom_paths_and_source_python(client):
    import sys
    seed(client)
    path = backup(client)
    guide = client.get('/api/workspaces/backups/' + path.name + '/restore-guide').json()
    assert guide['can_restore']
    command = guide['preflight_command']
    registry = client.app.state.workspaces
    assert str(registry.legacy.db_path) in command
    assert str(registry.legacy.master_key_path) in command
    assert str(sys.executable) in command
    assert 'restore-all.ps1' in command
    assert guide['apply_command'] == command + ' -Apply'


@pytest.mark.parametrize('missing', ['pdf', 'project-key', 'shared-key'])
def test_backup_does_not_publish_if_referenced_pdf_disappears_after_snapshot(client, monkeypatch, missing):
    seed(client)
    registry = client.app.state.workspaces
    client.post('/api/providers', json={'name': 'Local key owner', 'type': 'openai_chat', 'api_key': 'synthetic'})
    removed = {'pdf': registry.legacy.data_dir / 'pdfs' / 'same.pdf',
               'project-key': registry.legacy.master_key_path,
               'shared-key': registry.root / 'connections.key'}[missing]
    trigger = 'application/connections.sqlite' if missing == 'shared-key' else 'application/papermind.sqlite'
    original = application._write_file

    def remove_after_database(archive, source, member):
        entry = original(archive, source, member)
        if member == trigger:
            removed.unlink()
        return entry

    monkeypatch.setattr(application, '_write_file', remove_after_database)
    response = client.post('/api/workspaces/backups', json={'request_id': str(uuid4())})
    assert response.status_code == 409, response.text
    assert client.get('/api/workspaces/backups').json() == []
    assert not list(application.backup_directory(registry).glob('*.partial'))


@pytest.mark.parametrize('manifest', [None, [], {'created_at': 'invalid', 'projects': None}])
def test_damaged_backup_metadata_does_not_break_backup_listing(client, manifest):
    directory = application.backup_directory(client.app.state.workspaces)
    directory.mkdir(exist_ok=True)
    path = directory / f'papermind-all-{uuid4().hex}.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
    response = client.get('/api/workspaces/backups')
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1 and rows[0]['error'] and rows[0]['projects'] == []
