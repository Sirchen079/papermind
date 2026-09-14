"""Offline, verified whole-application restore with a retained rollback copy."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from app.archive.application import verify
from app.workspaces.runtime_lease import RuntimeLease

JOURNAL = '.application-restore.json'


def _remove(path, allowed):
    # All callers pass only a prevalidated, concrete target or scratch directory.
    if path not in allowed:
        raise ValueError('恢复清理路径未通过检查')
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def _probe_database(path):
    # Old builds do not hold RuntimeLease. Detect their Windows SQLite handles too.
    if os.name != 'nt' or not path.exists():
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    handle = create(str(path), 0xC0000000, 0, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError('数据库仍被占用或无法写入，请关闭 PaperMind 后重试：' + str(path))
    close(handle)


def restore(backup, data_dir, *, db_path=None, master_key_path=None, apply=False):
    backup = Path(backup).resolve()
    root = Path(data_dir).resolve()
    if root.parent == root:
        raise ValueError('请选择专门的数据目录，不能使用磁盘根目录')
    if root.exists() and not root.is_dir():
        raise ValueError('目标数据目录不是文件夹')
    raw_db = Path(db_path) if db_path else root / 'papermind.sqlite'
    raw_key = Path(master_key_path) if master_key_path else root / 'master.key'
    if raw_db.is_symlink() or raw_key.is_symlink():
        raise ValueError('数据库和密钥目标不能是符号链接')
    db, key = raw_db.resolve(), raw_key.resolve()
    if {db, key} & {root / JOURNAL, root / '.runtime-use.lock', root / 'api_token'}:
        raise ValueError('数据库和密钥路径与应用控制文件冲突')
    directories = [root / 'pdfs', root / 'workspaces']
    plan = [
        ('workspaces.sqlite', root / 'workspaces.sqlite', 'application/workspaces.sqlite'),
        ('connections.sqlite', root / 'connections.sqlite', 'application/connections.sqlite'),
        ('connections.key', root / 'connections.key', 'application/connections.key'),
        ('legacy.sqlite', db, 'application/papermind.sqlite'),
        ('legacy.key', key, 'application/master.key'),
        ('pdfs', directories[0], 'application/pdfs'),
        ('workspaces', directories[1], 'application/workspaces'),
        ('old-restore-marker', root / 'restore-manifest.json', None),
    ]
    for database in [root / 'workspaces.sqlite', root / 'connections.sqlite', db]:
        for suffix in ('-wal', '-shm', '-journal'):
            plan.append((database.name + suffix, Path(str(database) + suffix), None))
    targets = [target for _, target, _ in plan]
    if len({str(path).casefold() for path in targets}) != len(targets):
        raise ValueError('恢复目标之间存在路径冲突')
    for _, target, _ in plan:
        if target.is_symlink() or target == root or target == backup:
            raise ValueError('恢复目标路径不安全：' + str(target))
        if target not in directories and (target.is_dir() or any(target.is_relative_to(parent) for parent in directories)):
            raise ValueError('数据库、密钥和资料目录存在重叠')
        if target not in {db, key, *(Path(str(db) + suffix) for suffix in ('-wal', '-shm', '-journal'))} and not target.resolve().is_relative_to(root):
            raise ValueError('恢复目标越过应用数据目录')
    if any(backup.is_relative_to(directory) for directory in directories):
        raise ValueError('请将备份文件移到待恢复的原文与项目目录之外')
    checked = verify(backup)
    if not checked['ok']:
        raise ValueError('备份未通过校验：' + '；'.join(checked['errors']))
    result = {'ok': True, 'applied': False, 'data_dir': str(root), 'db_path': str(db),
              'master_key_path': str(key), 'projects': checked['projects'], 'recovery_directory': None}
    if not apply:
        return result
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        lease = RuntimeLease(root, exclusive=True)
    except OSError as exc:
        raise OSError('请关闭使用此数据目录的所有 PaperMind 窗口和服务，再执行整体恢复。') from exc
    journal = root / JOURNAL
    try:
        for _, target, _ in plan:
            if target not in directories:
                _probe_database(target)
        with tempfile.TemporaryDirectory(prefix='pm-stage-', dir=root.parent) as temporary:
            stage = Path(temporary).resolve()
            with zipfile.ZipFile(backup) as archive:
                # verify already validated every payload path; extract individually.
                for entry in checked['manifest']['files']:
                    target = stage / entry['path']
                    if not target.resolve().is_relative_to(stage):
                        raise ValueError('解压目标越过暂存目录')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry['path']) as source, target.open('wb') as output:
                        digest = hashlib.sha256()
                        size = 0
                        for chunk in iter(lambda: source.read(1024 * 1024), b''):
                            output.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    if size != entry['size_bytes'] or digest.hexdigest() != entry['sha256']:
                        raise ValueError('备份在预检后发生变化，请重新校验')
            recovery = Path(tempfile.mkdtemp(prefix='pm-before-', dir=root.parent)).resolve()
            records = []
            for index, (_, target, _) in enumerate(plan):
                saved = recovery / str(index)
                existed = target.exists()
                if existed:
                    _copy(target, saved)
                records.append({'target': str(target), 'saved': str(saved), 'existed': existed})
            record = {'backup': str(backup), 'recovery_directory': str(recovery), 'files': records}
            (recovery / 'recovery.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            with journal.open('w', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            allowed = set(targets)
            try:
                for _, target, member in plan:
                    _remove(target, allowed)
                    source = stage / member if member else None
                    if source and source.exists():
                        _copy(source, target)
            except BaseException as original:
                try:
                    for entry in records:
                        target = Path(entry['target'])
                        _remove(target, allowed)
                        if entry['existed']:
                            _copy(Path(entry['saved']), target)
                    journal.unlink()
                except BaseException as rollback:
                    raise OSError(f'恢复和回退均未完成。请保留恢复记录及副本：{recovery}。{original}；{rollback}') from original
                raise OSError(f'整体恢复失败，原资料已回退。回退副本：{recovery}。{original}') from original
            journal.unlink()
            result.update(applied=True, recovery_directory=str(recovery))
            return result
    finally:
        lease.close()
