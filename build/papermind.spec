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
import importlib

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

# PyInstaller execs the spec without __file__; it injects SPECPATH (the spec's
# directory). Fall back to CWD so the spec still works if run another way.
SPEC_DIR = Path(globals().get("SPECPATH") or os.getcwd()).resolve()
REPO = SPEC_DIR.parent
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
FRONTEND_DIST = Path(os.environ.get("PAPERMIND_BUILD_FRONTEND_DIST") or FRONTEND / "dist").resolve()

datas = []
binaries = []
hiddenimports = []

# A backend-only environment must never produce a desktop release. Importing
# these also verifies pywebview's transitive Python/.NET dependencies.
for module in ("webview", "proxy_tools", "bottle", "pythonnet", "clr_loader", "clr"):
    importlib.import_module(module)
    hiddenimports.append(module)

# Packages whose collection is required for the frozen MCP server (the S3
# external interface) to work; if collecting any of them fails, the build must
# fail instead of shipping a bundle that silently lacks MCP (R06).
MCP_CRITICAL = frozenset((
    "mcp_types",
    "sse_starlette",
    "opentelemetry",
    "jsonschema",
    "httpx2",
    "httpcore2",
    "jwt",
    "win32job",
    "win32api",
    "win32con",
    "pywintypes",
))

# Packages whose runtime dynamic imports / C extensions / data files the
# static analysis tends to miss. collect_all pulls modules + datas + binaries
# for each; failures for optional extras are ignored with a warning, while
# failures for the desktop shell or MCP-critical deps abort the build.
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
    "tiktoken_ext",
    "webview",
    "openpyxl",
    "docx",
    # MCP SDK (S3 external interface) runtime dependencies: the server stack
    # (app/integrations/mcp_server.py) imports mcp.server.lowlevel /
    # streamable_http / transport_security, mcp_types, sse_starlette,
    # opentelemetry, jsonschema, httpx2 and (Windows) pywin32 modules.
    # The `mcp` package itself is collected separately below because its
    # optional CLI subpackage needs the `typer` extra (not installed).
    "mcp_types",
    "sse_starlette",
    "opentelemetry",
    "jsonschema",
    "httpx2",
    "httpcore2",
    "jwt",
    "win32job",
    "win32api",
    "win32con",
    "pywintypes",
):
    try:
        d, b, h = collect_all(pkg)
    except Exception as exc:  # pragma: no cover - environment dependent
        if pkg == "webview":
            raise RuntimeError("Cannot build without the desktop dependencies") from exc
        if pkg in MCP_CRITICAL:
            raise RuntimeError(
                f"Cannot build without {pkg!r}: required by the frozen MCP server"
            ) from exc
        print(f"[spec] collect_all({pkg!r}) failed: {exc}")
        continue
    datas += d
    binaries += b
    hiddenimports += h

# MCP SDK: collect_all("mcp") fails because the optional `mcp.cli` subpackage
# imports typer (the `mcp[cli]` extra, not a PaperMind dependency). Collect the
# package with the CLI subpackage filtered out instead; the library modules
# (server/client/shared/os/cli are not imported by PaperMind) come along.
# Any error here must fail the build (R06): before the fix an unimported
# helper raised NameError that was caught and printed, silently skipping the
# whole MCP collection. An empty dynamic-lib list is legal (mcp is pure
# Python) and is not treated as a failure.
mcp_datas = collect_data_files("mcp")
mcp_binaries = collect_dynamic_libs("mcp")
mcp_hiddenimports = collect_submodules(
    "mcp", filter=lambda name: not name.startswith("mcp.cli"), on_error="ignore"
)
if not mcp_hiddenimports:
    raise RuntimeError(
        "collect_submodules('mcp') returned no modules; the frozen MCP server would be broken"
    )
datas += mcp_datas
binaries += mcp_binaries
hiddenimports += mcp_hiddenimports

# Read-only bundled resources. Destination dirs line up with app/paths.py.
datas += [
    (str(BACKEND / "alembic.ini"), "backend"),
    *[(str(path), str(Path("backend/migrations") / path.relative_to(BACKEND / "migrations").parent))
      for path in (BACKEND / "migrations").rglob("*")
      if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}],
    (str(BACKEND / "user_skills"), "backend/user_skills"),
    (str(BACKEND / "research_skills"), "backend/research_skills"),
    (str(BACKEND / "builtin_skills"), "backend/builtin_skills"),
    (str(REPO / "third_party"), "third_party"),
    (str(REPO / "THIRD_PARTY_NOTICES.md"), "."),
    (str(FRONTEND_DIST), "frontend/dist"),
    (str(SPEC_DIR / "assets" / "papermind.ico"), "desktop"),
    (str(SPEC_DIR / "vendor" / "webview2"), "desktop/webview2"),
    (str(SPEC_DIR / "vendor" / "llama_cpp"), "local_runtime"),
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
    version=str(SPEC_DIR / "version_info.txt"),
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPEC_DIR / "assets" / "papermind.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="PaperMind",
)
