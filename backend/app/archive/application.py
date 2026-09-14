"""Portable backups of the project directory, shared connections and all projects.

Each SQLite file uses its backup API. Shared connection references are retained;
the application directory and its encryption key travel in the same archive.
Only research data enters this format; prior backups and local UI caches stay out.
"""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
from uuid import UUID
import zipfile


FORMAT = 'application-backup'
PROJECT_ID = re.compile(r'^(legacy|[a-f0-9]{32})$')
BACKUP_NAME = re.compile(r'^papermind-all-[a-f0-9]{32}\.zip$')


@contextmanager
def _backup_lock(path, message='同一次整体备份仍在创建，请稍后查看备份列表'):
    handle = path.open('a+b')
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError(message) from exc
        yield
    finally:
        # OS releases the lease on process exit too; a crash cannot strand a retry.
        handle.close()


def backup_directory(registry):
    return registry.root / 'application-backups'


def resolve_backup(registry, filename):
    if not BACKUP_NAME.fullmatch(filename):
        raise FileNotFoundError('整体备份不存在')
    path = backup_directory(registry) / filename
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError('整体备份不存在')
    return path


def information(path):
    data = {'filename': path.name, 'size_bytes': path.stat().st_size,
            'modified_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        if (not isinstance(manifest, dict)
                or not isinstance(manifest.get('created_at'), str)
                or not isinstance(manifest.get('projects'), list)
                or any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
                       or not isinstance(row.get('name'), str) for row in manifest['projects'])):
            raise ValueError('备份清单格式异常，请保留文件并检查其他备份')
        datetime.fromisoformat(manifest['created_at'])
        data.update(created_at=manifest['created_at'], projects=manifest['projects'], error=None)
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        data.update(projects=[], error=str(exc))
    return data


def list_backups(registry):
    directory = backup_directory(registry)
    if not directory.is_dir():
        return []
    return [information(path) for path in sorted(directory.glob('papermind-all-*.zip'),
            key=lambda path: path.stat().st_mtime, reverse=True) if BACKUP_NAME.fullmatch(path.name) and not path.is_symlink()]


def _check_database(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('数据库完整性检查未通过')


def _snapshot(source, target):
    if not source.is_file():
        raise FileNotFoundError(f'数据库文件缺失：{source}')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=30)) as source_db:
        with closing(sqlite3.connect(target)) as dest:
            source_db.backup(dest)
    _check_database(target)


def _write_file(archive, source, member):
    before = source.stat()
    digest = hashlib.sha256()
    size = 0
    with source.open('rb') as stream, archive.open(member, 'w', force_zip64=True) as output:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or size != before.st_size:
        raise ValueError('备份期间资料文件发生变化，请稍后重新备份')
    return {'path': member, 'size_bytes': size, 'sha256': digest.hexdigest()}


def _project_prefix(project_id):
    return 'application' if project_id == 'legacy' else f'application/workspaces/{project_id}'


def create_backup(registry, request_id):
    from app.ingestion.pdf_storage import resolve_pdf
    backup_id = UUID(str(request_id)).hex
    directory = backup_directory(registry)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f'papermind-all-{backup_id}.zip'
    if destination.exists():
        return information(destination)
    # The OS lease excludes concurrent retries and is released on process exit.
    lock_path = destination.with_suffix('.lock')
    with _backup_lock(lock_path):
        with tempfile.TemporaryDirectory(prefix='pm-all-') as scratch:
            if destination.exists():
                return information(destination)
            scratch = Path(scratch)
            registry_snapshot = scratch / 'registry.sqlite'
            _snapshot(registry.path.resolve(), registry_snapshot)
            with closing(sqlite3.connect(registry_snapshot)) as db:
                db.row_factory = sqlite3.Row
                projects = [dict(row) for row in db.execute('SELECT * FROM workspace ORDER BY created_at,id')]
            ids = [row['id'] for row in projects]
            if 'legacy' not in ids or any(not PROJECT_ID.fullmatch(value) for value in ids):
                raise ValueError('项目目录包含无效标识，请先修复项目目录')
            manifest = {'archive_type': FORMAT, 'archive_schema_version': 1, 'app': 'PaperMind',
                        'created_at': datetime.now(timezone.utc).isoformat(), 'projects': projects, 'files': []}
            partial = destination.with_suffix('.partial')
            shared_ids = set()
            try:
                with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                    manifest['files'].append(_write_file(archive, registry_snapshot, 'application/workspaces.sqlite'))
                    for project in projects:
                        scope = registry.context(project['id'])
                        snapshot = scratch / 'project.sqlite'
                        _snapshot(scope.db_path.resolve(), snapshot)
                        pdf_root = (scope.data_dir / 'pdfs').resolve()
                        required_pdfs = set()
                        with closing(sqlite3.connect(snapshot)) as db:
                            for pid, value in db.execute('SELECT id,pdf_path FROM paper WHERE pdf_path IS NOT NULL'):
                                resolved = resolve_pdf(value, pdf_root)
                                if resolved is None:
                                    raise ValueError(f"项目“{project['name']}”的论文 #{pid} 缺少原文文件，请处理后重试")
                                relative = resolved.relative_to(pdf_root).as_posix()
                                required_pdfs.add(relative)
                                db.execute('UPDATE paper SET pdf_path=? WHERE id=?', (relative, pid))
                            shared_ids.update(row[0] for row in db.execute('SELECT shared_connection_id FROM provider WHERE shared_connection_id IS NOT NULL'))
                            needs_key = db.execute('SELECT 1 FROM provider WHERE shared_connection_id IS NULL AND api_key_encrypted IS NOT NULL LIMIT 1').fetchone()
                            if needs_key and not scope.master_key_path.is_file():
                                raise ValueError(f"项目“{project['name']}”缺少模型配置密钥，请先恢复密钥")
                            db.commit()
                        prefix = _project_prefix(scope.id)
                        manifest['files'].append(_write_file(archive, snapshot, prefix + '/papermind.sqlite'))
                        snapshot.unlink()
                        if scope.master_key_path.is_file():
                            manifest['files'].append(_write_file(archive, scope.master_key_path, prefix + '/master.key'))
                        elif needs_key:
                            raise ValueError(f"项目“{project['name']}”的配置密钥在备份期间发生变化，请稍后重试")
                        written_pdfs = set()
                        if pdf_root.is_dir():
                            for path in sorted(pdf_root.rglob('*')):
                                if path.is_file():
                                    if not path.resolve().is_relative_to(pdf_root):
                                        raise ValueError('原文目录中有指向目录外的文件，请先整理后备份')
                                    relative = path.relative_to(pdf_root).as_posix()
                                    manifest['files'].append(_write_file(archive, path, prefix + '/pdfs/' + relative))
                                    written_pdfs.add(relative)
                        # A file may disappear after the DB snapshot but before
                        # directory enumeration, without _write_file seeing it.
                        if required_pdfs - written_pdfs:
                            raise ValueError(f"项目“{project['name']}”的原文文件在备份期间发生变化，请稍后重试")
                    shared = registry.root / 'connections.sqlite'
                    if shared.exists():
                        shared_snapshot = scratch / 'shared.sqlite'
                        _snapshot(shared.resolve(), shared_snapshot)
                        with closing(sqlite3.connect(shared_snapshot)) as db:
                            known = {row[0] for row in db.execute('SELECT id FROM connection')}
                            needs_key = db.execute('SELECT 1 FROM connection WHERE api_key_encrypted IS NOT NULL LIMIT 1').fetchone()
                        if shared_ids - known:
                            raise ValueError('项目引用的共享连接缺失，请先处理连接配置')
                        if needs_key and not (registry.root / 'connections.key').is_file():
                            raise ValueError('共享连接密钥缺失，请先恢复密钥')
                        manifest['files'].append(_write_file(archive, shared_snapshot, 'application/connections.sqlite'))
                        if (registry.root / 'connections.key').is_file():
                            manifest['files'].append(_write_file(archive, registry.root / 'connections.key', 'application/connections.key'))
                        elif needs_key:
                            raise ValueError('共享连接密钥在备份期间发生变化，请稍后重试')
                    elif shared_ids:
                        raise ValueError('共享连接目录缺失，请先处理连接配置')
                    archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
        return information(destination)


def valid_member(name, project_ids):
    parts = PurePosixPath(name).parts
    if (not name or '\\' in name or name.startswith('/') or '/'.join(parts) != name
            or any(part in {'.', '..'} or part.endswith(('.', ' ')) or re.search(r'[\x00-\x1f<>:"|?*]', part)
                   or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part) for part in parts)):
        return False
    if name in {'application/workspaces.sqlite', 'application/connections.sqlite', 'application/connections.key'}:
        return True
    for project_id in project_ids:
        prefix = _project_prefix(project_id) + '/'
        if name.startswith(prefix):
            relative = name[len(prefix):]
            if relative in {'papermind.sqlite', 'master.key'} or relative.startswith('pdfs/'):
                return True
    return False


def verify(path):
    """Verify bytes, database integrity and project/reference topology, without live app state."""
    try:
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix='pm-check-') as scratch:
            members = archive.namelist()
            if len(members) != len(set(name.casefold() for name in members)):
                raise ValueError('备份存在重复或大小写冲突的文件路径')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('archive_type') != FORMAT or manifest.get('archive_schema_version') != 1:
                raise ValueError('这不是受支持的 PaperMind 整体备份')
            projects = manifest['projects']
            ids = [row['id'] for row in projects]
            if 'legacy' not in ids or len(set(ids)) != len(ids) or any(not PROJECT_ID.fullmatch(value) for value in ids):
                raise ValueError('备份项目目录无效')
            entries = manifest['files']
            if len(entries) != len({entry['path'].casefold() for entry in entries}):
                raise ValueError('文件清单有重复项')
            if set(members) != {'manifest.json', *(entry['path'] for entry in entries)}:
                raise ValueError('压缩包文件与清单不一致')
            required = {'application/workspaces.sqlite', *(_project_prefix(value) + '/papermind.sqlite' for value in ids)}
            if not required.issubset(members):
                raise ValueError('备份缺少项目数据库')
            shared_ids = set()
            known_connections = set()
            for entry in entries:
                name = entry['path']
                if not valid_member(name, ids):
                    raise ValueError('备份文件路径无效')
                digest = hashlib.sha256()
                size = 0
                database = name.endswith('.sqlite') and '/pdfs/' not in name
                local = Path(scratch) / 'check.sqlite'
                with archive.open(name) as stream:
                    output = local.open('wb') if database else None
                    try:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            size += len(chunk)
                            digest.update(chunk)
                            if output:
                                output.write(chunk)
                    finally:
                        if output:
                            output.close()
                if size != entry['size_bytes'] or digest.hexdigest() != entry['sha256']:
                    raise ValueError('备份文件校验失败：' + name)
                if database:
                    _check_database(local)
                    with closing(sqlite3.connect(local)) as db:
                        if name == 'application/workspaces.sqlite':
                            db.row_factory = sqlite3.Row
                            actual = {row['id']: dict(row) for row in db.execute('SELECT * FROM workspace')}
                            if actual != {row['id']: row for row in projects}:
                                raise ValueError('项目目录与备份清单不一致')
                        elif name == 'application/connections.sqlite':
                            known_connections = {row[0] for row in db.execute('SELECT id FROM connection')}
                            if db.execute('SELECT 1 FROM connection WHERE api_key_encrypted IS NOT NULL LIMIT 1').fetchone() and 'application/connections.key' not in members:
                                raise ValueError('备份缺少共享连接密钥')
                        else:
                            shared_ids.update(row[0] for row in db.execute('SELECT shared_connection_id FROM provider WHERE shared_connection_id IS NOT NULL'))
                            prefix = name.rsplit('/', 1)[0]
                            if db.execute('SELECT 1 FROM provider WHERE shared_connection_id IS NULL AND api_key_encrypted IS NOT NULL LIMIT 1').fetchone() and prefix + '/master.key' not in members:
                                raise ValueError('备份缺少项目配置密钥')
                            for (value,) in db.execute('SELECT pdf_path FROM paper WHERE pdf_path IS NOT NULL'):
                                if prefix + '/pdfs/' + value not in members:
                                    raise ValueError('备份缺少论文引用的原文文件')
                    local.unlink()
            if shared_ids - known_connections:
                raise ValueError('备份中存在缺失的共享连接引用')
            return {'ok': True, 'errors': [], 'projects': projects, 'file_count': len(entries), 'manifest': manifest}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, sqlite3.Error, zipfile.BadZipFile) as exc:
        return {'ok': False, 'errors': [str(exc)], 'projects': [], 'file_count': 0}


def restore_guide(registry, filename):
    import sys
    from app import paths
    path = resolve_backup(registry, filename)
    checked = verify(path)
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = '& ' + quote(paths.exe_dir() / 'restore-all.ps1')
    for flag, value in [('Backup', path), ('DataDir', registry.root),
                        ('DbPath', registry.legacy.db_path), ('MasterKeyPath', registry.legacy.master_key_path)]:
        command += ' -' + flag + ' ' + quote(value)
    if not paths.is_frozen():
        command += ' -PythonPath ' + quote(sys.executable)
    return {'can_restore': checked['ok'], 'errors': checked['errors'], 'projects': checked['projects'],
            'data_dir': str(registry.root), 'preflight_command': command, 'apply_command': command + ' -Apply'}
