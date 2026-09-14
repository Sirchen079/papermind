import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlmodel import Session

from app.config import get_settings
from app.db.engine import get_engine
from app.models import Paper


def paper_with_pdf():
    path = get_settings().data_dir / 'pdfs' / 'review.pdf'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'%PDF-1.4 original')
    with Session(get_engine()) as session:
        session.add(Paper(source='pdf', title='Required original', pdf_path=str(path)))
        session.commit()
    return path


@pytest.mark.parametrize('damage', ['future_schema', 'extra_file', 'duplicate_member', 'missing_reference'])
def test_project_verify_rejects_inconsistent_archive_contract(client, damage):
    paper_with_pdf()
    filename = client.post('/api/archive/backup').json()['filename']
    path = get_settings().data_dir / 'backups' / filename
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries['manifest.json'])
    if damage == 'future_schema':
        manifest['archive_schema_version'] = 999
    elif damage == 'extra_file':
        entries['unexpected.txt'] = b'extra'
    elif damage == 'missing_reference':
        entries.pop('pdfs/review.pdf')
        manifest['pdfs'] = {'count':0,'total_bytes':0,'files':[]}
    entries['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, 'w') as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
        if damage == 'duplicate_member':
            with pytest.warns(UserWarning, match='Duplicate name'):
                archive.writestr('manifest.json', entries['manifest.json'])
    result = client.post(f'/api/archive/backups/{filename}/verify').json()
    assert not result['ok'], result


def test_project_backup_rejects_missing_referenced_original(client):
    path = paper_with_pdf()
    path.unlink()
    response = client.post('/api/archive/backup')
    assert response.status_code == 409, response.text
    assert client.get('/api/archive/backups').json() == []


def test_project_backup_rejects_original_changed_while_writing(client, monkeypatch):
    path = paper_with_pdf()
    original = zipfile.ZipFile.open

    def changed(archive, name, mode='r', *args, **kwargs):
        member = name.filename if isinstance(name, zipfile.ZipInfo) else name
        if mode == 'w' and member == 'pdfs/review.pdf':
            path.write_bytes(b'%PDF-1.4 replaced while backing up, different length')
        return original(archive, name, mode, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'open', changed)
    response = client.post('/api/archive/backup')
    assert response.status_code == 409, response.text
    assert client.get('/api/archive/backups').json() == []


@pytest.mark.parametrize('manifest', [None, []])
def test_project_verify_reports_malformed_manifest_without_server_error(client, manifest):
    directory = get_settings().data_dir / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(directory / 'damaged.zip', 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
    response = client.post('/api/archive/backups/damaged.zip/verify')
    assert response.status_code == 200
    assert not response.json()['ok'] and response.json()['errors']


def test_concurrent_project_backups_do_not_share_partial_file(client, monkeypatch):
    from app.archive import service
    entered, release = Event(), Event()
    original = service._sqlite_snapshot

    def paused(*args):
        if not entered.is_set():
            entered.set()
            assert release.wait(20)
        return original(*args)

    monkeypatch.setattr(service, '_sqlite_snapshot', paused)
    # Force the same proposed filename even if the test crosses a second boundary.
    monkeypatch.setattr(service, '_backup_filename', lambda _: 'papermind-backup-concurrent.zip')
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, '/api/archive/backup')
        try:
            assert entered.wait(10)
            second = client.post('/api/archive/backup')
        finally:
            release.set()
        completed = first.result(timeout=20)
    assert completed.status_code == 200
    assert second.status_code == 409
    assert client.post('/api/archive/backups/' + completed.json()['filename'] + '/verify').json()['ok']
    # The lease is released, so a later request is allowed.
    assert client.post('/api/archive/backup').status_code == 200
