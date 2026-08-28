# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PaperMind desktop app.

Run via build/build.ps1 (which `cd`s into build/). All paths are resolved
relative to this spec file so the build works regardless of CWD.

Produces a onedir bundle at build/dist/PaperMind/ with the layout that
backend/app/paths.py expects under sys._MEIPASS:

    PaperMind/
    ├── PaperMind.exe
    └── _internal/
        ├── (python + deps)
        ├── backend/{alembic.ini, migrations/, user_skills/}
        └── frontend/dist/

User-writable data (SQLite, master.key, PDFs) is NOT stored here; app/config.py
defaults it to %LOCALAPPDATA%/PaperMind/data when frozen.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    copy_metadata,
)

# PyInstaller execs the spec without __file__; it injects SPECPATH (the spec's
# directory). Fall back to CWD so the spec still works if run another way.
SPEC_DIR = Path(globals().get("SPECPATH") or os.getcwd()).resolve()
REPO = SPEC_DIR.parent
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"

datas = []
binaries = []
hiddenimports = []

# Packages whose runtime dynamic imports / C extensions / data files the
# static analysis tends to miss. collect_all pulls modules + datas + binaries
# for each; failures (e.g. a package not installed) are ignored so a partial
# environment still produces a build with a clear warning.
for pkg in (
    "litellm",
    "sqlite_vec",
    "alembic",
    "pymupdf",
    "fitz",
    "arxiv",
    "bibtexparser",
    "uvicorn",
    "httptools",
    "websockets",
):
    try:
        d, b, h = collect_all(pkg)
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[spec] collect_all({pkg!r}) failed: {exc}")
        continue
    datas += d
    binaries += b
    hiddenimports += h

# Read-only bundled resources. Destination dirs line up with app/paths.py.
datas += [
    (str(BACKEND / "alembic.ini"), "backend"),
    (str(BACKEND / "migrations"), "backend/migrations"),
    (str(BACKEND / "user_skills"), "backend/user_skills"),
    (str(FRONTEND / "dist"), "frontend/dist"),
]

# Some libs introspect their own installed distribution metadata at runtime.
for dist in ("litellm", "pydantic-settings", "sqlmodel", "fastapi"):
    try:
        datas += copy_metadata(dist)
    except Exception as exc:  # pragma: no cover
        print(f"[spec] copy_metadata({dist!r}) failed: {exc}")

a = Analysis(
    [str(BACKEND / "app" / "launcher.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "respx", "_pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PaperMind",
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="PaperMind",
)
