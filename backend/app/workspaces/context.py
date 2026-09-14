from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceContext:
    id: str
    data_dir: Path
    db_path: Path
    master_key_path: Path
    name: str = ''
    goal: str = ''
    application_dir: Path | None = None


current_workspace: ContextVar[WorkspaceContext | None] = ContextVar('papermind_workspace', default=None)


@contextmanager
def bind_workspace(context: WorkspaceContext):
    token = current_workspace.set(context)
    try:
        yield context
    finally:
        current_workspace.reset(token)
