from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.archive import application_restore as recovery
from app.db.engine import get_engine
from app.main import create_app
from app.workspaces.context import bind_workspace
from test_application_archive import backup, seed


def stop(client):
    registry = client.app.state.workspaces
    client.app.state.release_runtime_lease()
    for row in registry.list():
        with bind_workspace(registry.context(row['id'])):
            get_engine().dispose()


def title(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT title FROM paper').fetchone()[0]


def change_title(path, value):
    with closing(sqlite3.connect(path)) as db:
        db.execute('UPDATE paper SET title=?', (value,))
        db.commit()


def test_restore_dry_run_then_custom_target_and_real_startup(client, env, monkeypatch):
    wid, _ = seed(client)
    archive = backup(client)
    root = env / 'target'
    custom_db = env / 'custom.sqlite'
    custom_key = env / 'custom.key'
    dry = recovery.restore(archive, root, db_path=custom_db, master_key_path=custom_key)
    assert dry['ok'] and not dry['applied'] and not root.exists() and not custom_db.exists()
    restored = recovery.restore(archive, root, db_path=custom_db, master_key_path=custom_key, apply=True)
    assert restored['applied'] and Path(restored['recovery_directory']).is_dir()
    assert title(custom_db) == 'Legacy private'
    assert title(root / 'workspaces' / wid / 'papermind.sqlite') == 'B private'
    assert not (root / recovery.JOURNAL).exists()
    monkeypatch.setenv('PAPERMIND_DATA_DIR', str(root))
    monkeypatch.setenv('PAPERMIND_DB_PATH', str(custom_db))
    monkeypatch.setenv('PAPERMIND_MASTER_KEY_PATH', str(custom_key))
    restarted = TestClient(create_app())
    assert all(row['available'] for row in restarted.get('/api/workspaces').json())
    assert restarted.get('/api/w/' + wid + '/papers').json()['items'][0]['title'] == 'B private'


def test_running_app_blocks_restore_before_any_replacement(client):
    seed(client)
    archive = backup(client)
    registry = client.app.state.workspaces
    with pytest.raises(OSError, match='关闭'):
        recovery.restore(archive, registry.root, db_path=registry.legacy.db_path,
                         master_key_path=registry.legacy.master_key_path, apply=True)
    assert title(registry.legacy.db_path) == 'Legacy private'
    assert not (registry.root / recovery.JOURNAL).exists()


def test_failure_after_replacements_rolls_back_all_nodes_and_preserves_other_files(client, monkeypatch):
    wid, _ = seed(client)
    archive = backup(client)
    registry = client.app.state.workspaces
    stop(client)
    change_title(registry.legacy.db_path, 'New legacy work')
    change_title(registry.context(wid).db_path, 'New B work')
    pdf = registry.root / 'pdfs' / 'same.pdf'
    pdf.write_bytes(b'%PDF newer local material')
    token = registry.root / 'api_token'
    token.write_text('keep-local-token')
    desktop = registry.root / 'desktop'
    desktop.mkdir(exist_ok=True)
    (desktop / 'window.json').write_text('keep-ui-state')
    copy = recovery._copy
    def fail(source, target):
        if 'pm-stage-' in str(source) and target == registry.root / 'workspaces':
            raise OSError('synthetic copy failure after replacing other files')
        return copy(source, target)
    monkeypatch.setattr(recovery, '_copy', fail)
    with pytest.raises(OSError, match='原资料已回退'):
        recovery.restore(archive, registry.root, db_path=registry.legacy.db_path,
                         master_key_path=registry.legacy.master_key_path, apply=True)
    assert title(registry.legacy.db_path) == 'New legacy work'
    assert title(registry.context(wid).db_path) == 'New B work'
    assert pdf.read_bytes() == b'%PDF newer local material'
    assert token.read_text() == 'keep-local-token'
    assert (desktop / 'window.json').read_text() == 'keep-ui-state'
    assert archive.is_file()
    assert not (registry.root / recovery.JOURNAL).exists()
    assert list(registry.root.parent.glob('pm-before-*/recovery.json'))


def test_incomplete_rollback_blocks_startup_and_successful_retry_recovers(client, monkeypatch):
    seed(client)
    archive = backup(client)
    registry = client.app.state.workspaces
    stop(client)
    copy = recovery._copy
    def fail(source, target):
        if target == registry.root / 'workspaces' and ('pm-stage-' in str(source) or 'pm-before-' in str(source)):
            raise OSError('synthetic interrupted file copy')
        return copy(source, target)
    monkeypatch.setattr(recovery, '_copy', fail)
    with pytest.raises(OSError, match='恢复和回退均未完成'):
        recovery.restore(archive, registry.root, db_path=registry.legacy.db_path,
                         master_key_path=registry.legacy.master_key_path, apply=True)
    assert (registry.root / recovery.JOURNAL).is_file()
    with pytest.raises(OSError, match='上次整体恢复尚未完成'):
        create_app()
    monkeypatch.setattr(recovery, '_copy', copy)
    assert recovery.restore(archive, registry.root, db_path=registry.legacy.db_path,
                            master_key_path=registry.legacy.master_key_path, apply=True)['applied']
    assert not (registry.root / recovery.JOURNAL).exists()
    restarted = TestClient(create_app())
    assert all(row['available'] for row in restarted.get('/api/workspaces').json())


@pytest.mark.parametrize('target', ['workspaces.sqlite', 'pdfs/nested.sqlite', '.application-restore.json', 'api_token'])
def test_overlapping_or_control_file_targets_fail_before_changes(client, target):
    seed(client)
    archive = backup(client)
    root = client.app.state.workspaces.root
    with pytest.raises(ValueError):
        recovery.restore(archive, root, db_path=root / target, apply=True)
    assert not (root / recovery.JOURNAL).exists()


def test_invalid_backup_does_not_create_target_directory(client, env):
    root = env / 'must-not-exist'
    invalid = env / 'invalid.zip'
    invalid.write_bytes(b'not a zip')
    with pytest.raises(ValueError, match='备份未通过校验'):
        recovery.restore(invalid, root, apply=True)
    assert not root.exists()


@pytest.mark.skipif(shutil.which('powershell') is None, reason='PowerShell is required')
def test_actual_restore_script_handles_spaces_trailing_slash_and_custom_paths(client, env):
    seed(client)
    archive = backup(client)
    root = env / 'restored space'
    custom_db = env / 'custom database.sqlite'
    custom_key = env / 'custom master.key'
    script = Path(__file__).resolve().parents[2] / 'restore-all.ps1'
    arguments = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                 '-Backup', str(archive), '-DataDir', str(root) + '\\', '-DbPath', str(custom_db),
                 '-MasterKeyPath', str(custom_key), '-PythonPath', sys.executable]
    process_env = dict(os.environ)  # Windows environment keys are case-insensitive.
    dry = subprocess.run(arguments, env=process_env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert not root.exists()
    applied = subprocess.run([*arguments, '-Apply'], env=process_env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert title(custom_db) == 'Legacy private'
    assert (root / 'workspaces.sqlite').is_file()
    assert custom_key.is_file()
