"""Centralized path resolution for dev and frozen (PyInstaller) modes.

In the source tree the layout is::

    <repo>/backend/app/paths.py        (this file)
    <repo>/backend/alembic.ini
    <repo>/backend/migrations/...
    <repo>/backend/user_skills/...
    <repo>/frontend/dist/...

When frozen by PyInstaller (onedir), data files bundled via ``datas=[...]``
land under ``sys._MEIPASS`` (the ``_internal/`` directory next to the exe),
and the exe itself lives one level above. User-writable data must NOT go
inside the bundle (Program Files is read-only for standard users), so the
default data dir switches to ``%LOCALAPPDATA%/PaperMind/data``.

Resolution priority for every path here:

1. An explicit ``PAPERMIND_*`` env var (lets tests / power users override).
2. The frozen bundle layout (``sys._MEIPASS`` for read-only resources,
   ``sys.executable`` parent for things that must sit beside the exe).
3. The source-tree layout used during development.

Keeping this in one module lets ``main.py`` / ``skills_api.py`` / ``config.py``
share one source of truth instead of each hard-coding ``__file__`` walks.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def _meipass() -> Path:
    """Directory where PyInstaller drops bundled data files (``_internal/``)."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base).resolve() if base else Path(sys.executable).resolve().parent


def exe_dir() -> Path:
    """Directory holding the runnable exe (frozen) or the repo root (dev).

    In dev this returns the repo root so callers can reason about
    ``frontend/dist`` the same way the old ``__file__`` walk did.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # backend/app/paths.py -> repo root
    return Path(__file__).resolve().parents[2]


def backend_dir() -> Path:
    """Directory containing ``alembic.ini`` and ``migrations/``."""
    env = os.environ.get("PAPERMIND_BACKEND_DIR")
    if env:
        return Path(env).resolve()
    if is_frozen():
        # Bundled as datas -> _internal/backend
        return _meipass() / "backend"
    # backend/app/paths.py -> backend
    return Path(__file__).resolve().parents[1]


def migrations_dir() -> Path:
    env = os.environ.get("PAPERMIND_MIGRATIONS_DIR")
    if env:
        return Path(env).resolve()
    return backend_dir() / "migrations"


def alembic_ini() -> Path:
    return backend_dir() / "alembic.ini"


def user_skills_dir() -> Path:
    env = os.environ.get("PAPERMIND_USER_SKILLS_DIR")
    if env:
        return Path(env).resolve()
    return backend_dir() / "user_skills"


def frontend_dist() -> Path:
    env = os.environ.get("PAPERMIND_FRONTEND_DIST")
    if env:
        return Path(env).resolve()
    if is_frozen():
        return _meipass() / "frontend" / "dist"
    return exe_dir() / "frontend" / "dist"


def default_data_dir() -> Path:
    """Where SQLite + master key + PDFs live.

    Frozen: ``%LOCALAPPDATA%/PaperMind/data`` (writable per-user store).
    Dev: ``data`` relative to CWD (preserves existing behavior).
    """
    env = os.environ.get("PAPERMIND_DATA_DIR")
    if env:
        return Path(env).resolve()
    if is_frozen():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "PaperMind" / "data"
    return Path("data")
