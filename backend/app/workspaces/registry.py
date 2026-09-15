"""Application-wide directory; research contents live in separate databases."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
import re
import sqlite3
from uuid import uuid4
from threading import RLock

from app.workspaces.context import WorkspaceContext, bind_workspace


class WorkspaceRegistry:
    def __init__(self, settings):
        self.root = settings.data_dir.resolve()
        self.legacy = WorkspaceContext('legacy', self.root, settings.resolved_db_path.resolve(),
                                       settings.resolved_master_key_path.resolve(), application_dir=self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'workspaces.sqlite'
        self._errors: dict[str, str] = {}
        self._lock = RLock()
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS workspace ('
                       'id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL DEFAULT \'\', '
                       'archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
            if 'initialized' not in {row[1] for row in db.execute('PRAGMA table_info(workspace)')}:
                db.execute('ALTER TABLE workspace ADD COLUMN initialized INTEGER NOT NULL DEFAULT 1')
            now = self.now()
            db.execute('INSERT OR IGNORE INTO workspace(id,name,created_at,updated_at,initialized) VALUES(?,?,?,?,?)',
                       ('legacy', '原有研究空间', now, now, int(self.legacy.db_path.exists())))

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def list(self):
        with self.connection() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM workspace ORDER BY created_at,id')]
        for row in rows:
            reason = self.unavailable_reason(row['id'])
            row.update(available=not reason, unavailable_reason=reason)
        return rows

    def mark_ready(self, workspace_id):
        with self.connection() as db:
            db.execute('UPDATE workspace SET initialized=1 WHERE id=?', (workspace_id,))
        with self._lock:
            self._errors.pop(workspace_id, None)

    def mark_unavailable(self, workspace_id, reason):
        with self._lock:
            self._errors[workspace_id] = reason

    def unavailable_reason(self, workspace_id):
        with self._lock:
            error = self._errors.get(workspace_id)
        if error:
            return error
        context = self.context(workspace_id)
        try:
            with context.db_path.open('rb') as file:
                if file.read(16) != b'SQLite format 3\x00':
                    return '项目数据库格式异常。请关闭应用并从该项目的备份恢复后重新启动。'
        except FileNotFoundError:
            return '找不到项目数据库。请检查数据目录或从该项目的备份恢复后重新启动。'
        except OSError:
            return '项目数据库暂时无法读取。请检查文件权限和磁盘状态。'
        return None

    def validate_existing(self, workspace_id):
        """Check before migrations, so a missing database is never re-created."""
        row = self.get(workspace_id)
        if not row['initialized'] and not self.context(workspace_id).db_path.exists():
            return  # First launch of a new installation, including a failed first setup.
        reason = self.unavailable_reason(workspace_id)
        if reason:
            raise ValueError(reason)
        uri = self.context(workspace_id).db_path.as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('项目数据库完整性检查未通过，请从该项目的备份恢复。')

    def get(self, workspace_id):
        if workspace_id != 'legacy' and not re.fullmatch(r'[a-f0-9]{32}', workspace_id):
            raise LookupError('研究项目不存在')
        with self.connection() as db:
            row = db.execute('SELECT * FROM workspace WHERE id=?', (workspace_id,)).fetchone()
        if row is None:
            raise LookupError('研究项目不存在')
        return dict(row)

    def context(self, workspace_id):
        row = self.get(workspace_id)
        if workspace_id == 'legacy':
            return replace(self.legacy, name=row['name'], goal=row['goal'])
        directory = self.root / 'workspaces' / workspace_id
        return WorkspaceContext(workspace_id, directory, directory / 'papermind.sqlite', directory / 'master.key', row['name'], row['goal'], self.root)

    def create(self, name, goal=''):
        workspace_id = uuid4().hex
        directory = self.root / 'workspaces' / workspace_id
        context = WorkspaceContext(workspace_id, directory, directory / 'papermind.sqlite', directory / 'master.key', application_dir=self.root)
        # Publish only after schema creation succeeds. A failed setup never
        # exposes a half-initialized database in the project selector.
        from app.main import _run_migrations, _load_default_skills
        with bind_workspace(context):
            _run_migrations()
            _load_default_skills()
        now = self.now()
        with self.connection() as db:
            db.execute('INSERT INTO workspace(id,name,goal,created_at,updated_at) VALUES(?,?,?,?,?)',
                       (workspace_id, name.strip(), goal.strip(), now, now))
        return self.get(workspace_id)

    def update(self, workspace_id, changes):
        row = self.get(workspace_id)
        for key in ('name', 'goal', 'archived'):
            if key in changes:
                row[key] = changes[key].strip() if isinstance(changes[key], str) else changes[key]
        with self.connection() as db:
            db.execute('UPDATE workspace SET name=?,goal=?,archived=?,updated_at=? WHERE id=?',
                       (row['name'], row['goal'], row['archived'], self.now(), workspace_id))
        return self.get(workspace_id)
