# P0a — Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the runnable backend foundation of the paper-management app: a FastAPI service with SQLite (WAL) + sqlite-vec loader + Alembic, the core data models, Fernet encryption for API keys, a LiteLLM-backed multi-provider layer (OpenAI Chat / OpenAI Responses / Anthropic / OpenAI-compatible) with auto model-list fetching and per-call token recording, and REST APIs for Settings / Providers / Models / Usage.

**Architecture:** FastAPI app factory; synchronous SQLAlchemy-via-SQLModel against SQLite in WAL mode (FastAPI serves sync endpoints from its threadpool — sufficient for local single-user, avoids async-SQLite complexity). Schema managed by Alembic. A `ProviderClient` wraps LiteLLM for unified `complete()` calls and routes per-call token usage into a `TokenUsage` table. API keys are Fernet-encrypted at rest under a machine-local master key.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, SQLModel (SQLAlchemy 2.0), Alembic, LiteLLM, cryptography (Fernet), pydantic-settings, httpx, sqlite-vec. Tests: pytest, respx (httpx mocking).

## Global Constraints

- **Platform:** Windows 11; bash shell; working dir `g:/vibe coding/论文管理`. Backend lives under `backend/`.
- **Python:** >=3.11. Use a venv at `backend/.venv` (gitignored).
- **No auth (default):** local single-user; no login in P0a.
- **Encryption:** every API key stored Fernet-encrypted at rest; master key at `backend/data/master.key` (auto-generated on first run, gitignored). Plaintext keys never logged.
- **DB:** SQLite in WAL mode; connection string `sqlite:///<data_dir>/papermind.sqlite`. Schema via Alembic only (`alembic upgrade head` on startup); never `create_all` in app code.
- **sqlite-vec:** loaded lazily with graceful degradation — if the bundled SQLite lacks extension support (common on Windows), the app still runs; vector features gate on a successful load. Actual vector tables arrive in P3.
- **Provider types (exact enum):** `openai_chat`, `openai_responses`, `anthropic`, `openai_compat`.
- **Token accounting:** every LLM call records one `TokenUsage` row (provider_id, model, prompt/completion/total, request_kind, ref_id, day).
- **Tests:** each test uses an isolated temp DB + temp data dir via env vars; no shared state. Run with `pytest -q` from `backend/`.
- **Native capabilities first (spec §1.3):** the agent prefers provider-native tools (web search, code execution) passed through LiteLLM over custom reimplementations. P0a's `complete()` is tool-less by design; its signature gains a `tools` param (custom + native pass-through) in P2 — no rework needed.
- **Commit:** after every task, conventional-commit messages (`feat:`, `chore:`, `test:`).

---

## File Structure

```
backend/
├── pyproject.toml                     # deps + project metadata
├── alembic.ini                        # alembic config
├── .gitignore                         # .venv, data/, __pycache__
├── app/
│   ├── __init__.py
│   ├── main.py                        # create_app() factory, startup migration, mounts routers
│   ├── config.py                      # Settings (pydantic-settings), get_settings()
│   ├── logging_setup.py               # structured-ish logging config
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py                  # engine + WAL pragmas + get_session dependency
│   │   └── vec.py                     # sqlite-vec lazy loader (graceful degradation)
│   ├── models/
│   │   ├── __init__.py                # imports all models so SQLModel.metadata is populated
│   │   ├── base.py                    # SQLModel base + mixins
│   │   ├── setting.py                 # Setting
│   │   ├── provider.py                # Provider, Model
│   │   └── usage.py                   # TokenUsage, TokenUsageDaily
│   ├── security/
│   │   ├── __init__.py
│   │   ├── master_key.py              # load/generate master key file
│   │   └── crypto.py                  # Fernet encrypt/decrypt
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── routing.py                 # provider_type -> litellm call args
│   │   └── client.py                  # ProviderClient: complete(), list_models()
│   └── api/
│       ├── __init__.py
│       ├── deps.py                    # shared deps (get_session, get_crypto)
│       ├── health.py                  # GET /api/health
│       ├── settings_api.py            # Setting CRUD
│       ├── providers_api.py           # Provider CRUD + POST /models refresh
│       ├── models_api.py              # Model list
│       └── usage_api.py               # Usage aggregates
├── migrations/
│   ├── env.py                         # Alembic env, target_metadata = SQLModel.metadata
│   ├── script.py.mako
│   └── versions/                      # generated migrations
└── tests/
    ├── conftest.py                    # tmp db/data/key fixtures, client fixture
    ├── test_health.py
    ├── test_engine.py
    ├── test_models.py
    ├── test_migration.py
    ├── test_crypto.py
    ├── test_routing.py
    ├── test_provider_client.py
    ├── test_settings_api.py
    ├── test_providers_api.py
    ├── test_models_api.py
    └── test_usage_api.py
```

Each file has one responsibility; files that change together (e.g. a model + its migration + its API) are co-located by domain in later plans.

---

## Task 1: Project scaffold, config, logging, health endpoint

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.gitignore`
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/app/config.py`
- Create: `backend/app/logging_setup.py`
- Create: `backend/app/api/__init__.py` (empty)
- Create: `backend/app/api/health.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI` (in `app.main`); `get_settings() -> Settings` (in `app.config`); env-var-driven config (`PAPERMIND_DATA_DIR`, `PAPERMIND_DB_PATH`, `PAPERMIND_MASTER_KEY_PATH`).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_health.py`:
```python
from fastapi.testclient import TestClient


def test_health_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_health.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'` (no app yet).

- [ ] **Step 3: Write pyproject + gitignore**

`backend/pyproject.toml`:
```toml
[project]
name = "papermind-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlmodel>=0.0.22",
  "alembic>=1.13",
  "litellm>=1.50",
  "cryptography>=43",
  "pydantic-settings>=2.5",
  "httpx>=0.27",
  "sqlite-vec>=0.1.6",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "respx>=0.21"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]
```

`backend/.gitignore`:
```
.venv/
__pycache__/
*.pyc
data/
pytest_cache/
```

- [ ] **Step 4: Create venv and install**

Run:
```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -U pip
.venv/Scripts/python -m pip install -e ".[dev]"
```
Expected: install succeeds; `pip show fastapi` lists it.

- [ ] **Step 5: Write config**

`backend/app/config.py`:
```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERMIND_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    db_path: Path | None = None          # default: data_dir/papermind.sqlite
    master_key_path: Path | None = None  # default: data_dir/master.key

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path if self.db_path is not None else self.data_dir / "papermind.sqlite"

    @property
    def resolved_master_key_path(self) -> Path:
        return (
            self.master_key_path
            if self.master_key_path is not None
            else self.data_dir / "master.key"
        )


def get_settings() -> Settings:
    # Re-read each call so tests can override via env vars.
    return Settings()
```

- [ ] **Step 6: Write logging setup**

`backend/app/logging_setup.py`:
```python
import logging


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
```

- [ ] **Step 7: Write health router + app factory**

`backend/app/api/health.py`:
```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

`backend/app/main.py`:
```python
from fastapi import FastAPI

from app.api.health import router as health_router
from app.logging_setup import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="PaperMind")
    app.include_router(health_router, prefix="/api")
    return app
```

- [ ] **Step 8: Write conftest fixtures**

`backend/tests/conftest.py`:
```python
import os
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so `import app` works without install.
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("PAPERMIND_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PAPERMIND_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("PAPERMIND_MASTER_KEY_PATH", str(tmp_path / "master.key"))
    return tmp_path


@pytest.fixture
def client(env):
    from app.main import create_app
    return TestClient(create_app())
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_health.py -q`
Expected: PASS (1 passed).

- [ ] **Step 10: Commit**

```bash
cd "g:/vibe coding/论文管理"
git add backend/pyproject.toml backend/.gitignore backend/app backend/tests
git commit -m "feat(backend): scaffold FastAPI app with config, logging, health endpoint"
```

---

## Task 2: Database engine (WAL) + session dependency + sqlite-vec lazy loader

**Files:**
- Create: `backend/app/db/__init__.py` (empty)
- Create: `backend/app/db/vec.py`
- Create: `backend/app/db/engine.py`
- Create: `backend/tests/test_engine.py`

**Interfaces:**
- Produces: `make_engine(db_path: Path) -> Engine` (WAL enabled, sqlite-vec best-effort loaded); `get_session() -> Iterator[Session]` FastAPI dependency; `vec_available() -> bool`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_engine.py`:
```python
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.engine import make_engine, vec_available


def test_engine_enables_wal(tmp_path):
    eng = make_engine(tmp_path / "x.sqlite")
    with eng.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"
    assert isinstance(eng, Engine)


def test_vec_loader_is_callable_and_does_not_crash():
    # Loader must exist; availability depends on platform build.
    assert callable(vec_available)
    assert isinstance(vec_available(), bool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.engine'`.

- [ ] **Step 3: Write sqlite-vec lazy loader (graceful degradation)**

`backend/app/db/vec.py`:
```python
"""sqlite-vec loader with graceful degradation.

The bundled SQLite on Windows often lacks load-extension support. We attempt
to load sqlite-vec; if it fails we log and continue (vector features disabled).
"""
import logging

from sqlalchemy import Engine, event

_log = logging.getLogger(__name__)
_VEC_OK: bool | None = None


def _try_load(connection) -> None:
    global _VEC_OK
    if _VEC_OK is False:
        return
    try:
        import sqlite_vec  # type: ignore

        dbapi_conn = connection.connection
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        _VEC_OK = True
    except Exception as exc:  # noqa: BLE001
        if _VEC_OK is None:
            _log.warning("sqlite-vec not available: %s (vector features disabled)", exc)
        _VEC_OK = False


def attach(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        # Defer; wrap in a pseudo-connection for the loader signature.
        try:
            _try_load(_PseudoConn(dbapi_conn))
        except Exception:  # noqa: BLE001
            _VEC_OK = False


class _PseudoConn:
    """Adapter exposing .connection for _try_load."""

    def __init__(self, dbapi_conn) -> None:  # noqa: ANN001
        self.connection = dbapi_conn


def vec_available() -> bool:
    if _VEC_OK is None:
        _VEC_OK = False  # not yet attached to any real connection
    return bool(_VEC_OK)
```

- [ ] **Step 4: Write engine + session**

`backend/app/db/engine.py`:
```python
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.db import vec as vec_mod


def make_engine(db_path: Path) -> Engine:
    from sqlalchemy import create_engine

    url = f"sqlite:///{db_path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        # best-effort sqlite-vec
        try:
            import sqlite_vec  # type: ignore

            dbapi_conn.enable_load_extension(True)
            sqlite_vec.load(dbapi_conn)
            vec_mod._VEC_OK = True  # noqa: SLF001
        except Exception:  # noqa: BLE001
            vec_mod._VEC_OK = False

    return engine


# Module-level engine bound lazily on first request.
_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        from app.config import get_settings

        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = make_engine(settings.resolved_db_path)
    return _engine


def reset_engine_for_tests() -> None:
    """Tests call this to drop the cached engine between cases."""
    global _engine
    _engine = None


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def vec_available() -> bool:
    return vec_mod.vec_available()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_engine.py -q`
Expected: PASS (2 passed). (sqlite-vec may or may not load — `vec_available()` returns a bool either way.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/db backend/tests/test_engine.py
git commit -m "feat(db): SQLite WAL engine, session dependency, sqlite-vec lazy loader"
```

---

## Task 3: SQLModel entities (Setting, Provider, Model, TokenUsage, TokenUsageDaily)

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/base.py`
- Create: `backend/app/models/setting.py`
- Create: `backend/app/models/provider.py`
- Create: `backend/app/models/usage.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Setting(key, value)`, `Provider(name, type, base_url, api_key_encrypted, ...)`, `Model(provider_id, model_id, display_name, context_window, supports_tools, supports_streaming, fetched_at, is_manual)`, `TokenUsage(provider_id, model, prompt_tokens, completion_tokens, total_tokens, request_kind, ref_id, day)`, `TokenUsageDaily(day, provider_id, model, request_kind, total_tokens, call_count)`. All tables named explicitly to keep migration names stable.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_models.py`:
```python
from datetime import date
from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session, select

from app.db.engine import make_engine
from app.models import Setting, Provider, Model, TokenUsage, TokenUsageDaily


def test_setting_roundtrip(tmp_path):
    eng = make_engine(tmp_path / "m.sqlite")
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Setting(key="theme", value="dark"))
        s.commit()
        row = s.exec(select(Setting).where(Setting.key == "theme")).one()
        assert row.value == "dark"


def test_provider_and_model_roundtrip(tmp_path):
    eng = make_engine(tmp_path / "m.sqlite")
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        p = Provider(name="openai", type="openai_chat", base_url="https://api.openai.com/v1", api_key_encrypted="enc")
        s.add(p); s.commit(); s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", display_name="GPT-4o", context_window=128000))
        s.commit()
        m = s.exec(select(Model).where(Model.model_id == "gpt-4o")).one()
        assert m.provider_id == p.id


def test_token_usage_persists(tmp_path):
    eng = make_engine(tmp_path / "m.sqlite")
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(TokenUsage(provider_id=1, model="gpt-4o", prompt_tokens=10, completion_tokens=5,
                         total_tokens=15, request_kind="chat", day=date(2026, 6, 28)))
        s.commit()
        assert s.exec(select(TokenUsage)).first() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'Setting' ...`.

- [ ] **Step 3: Write base + entities**

`backend/app/models/base.py`:
```python
from datetime import datetime
from sqlmodel import SQLModel, Field


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
```

`backend/app/models/setting.py`:
```python
from sqlmodel import SQLModel, Field


class Setting(SQLModel, table=True):
    __tablename__ = "setting"
    key: str = Field(primary_key=True)
    value: str | None = None
```

`backend/app/models/provider.py`:
```python
from datetime import datetime
from sqlmodel import SQLModel, Field


class Provider(SQLModel, table=True):
    __tablename__ = "provider"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    type: str  # openai_chat | openai_responses | anthropic | openai_compat
    base_url: str | None = None
    api_key_encrypted: str | None = None
    extra_headers_json: str | None = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class Model(SQLModel, table=True):
    __tablename__ = "model"
    id: int | None = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="provider.id", index=True)
    model_id: str = Field(index=True)
    display_name: str | None = None
    context_window: int | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    role_default: str | None = None  # summary | extraction | chat | deep | embedding
    fetched_at: datetime | None = None
    is_manual: bool = False
```

`backend/app/models/usage.py`:
```python
from datetime import date, datetime
from sqlmodel import SQLModel, Field


class TokenUsage(SQLModel, table=True):
    __tablename__ = "tokenusage"
    id: int | None = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="provider.id", index=True)
    model: str = Field(index=True)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_kind: str = Field(index=True)  # ingest | chat | skill | embed
    ref_id: str | None = None
    day: date = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class TokenUsageDaily(SQLModel, table=True):
    __tablename__ = "tokenusagedaily"
    day: date = Field(primary_key=True)
    provider_id: int = Field(primary_key=True)
    model: str = Field(primary_key=True)
    request_kind: str = Field(primary_key=True)
    total_tokens: int = 0
    call_count: int = 0
```

`backend/app/models/__init__.py`:
```python
from app.models.setting import Setting
from app.models.provider import Provider, Model
from app.models.usage import TokenUsage, TokenUsageDaily

__all__ = ["Setting", "Provider", "Model", "TokenUsage", "TokenUsageDaily"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models backend/tests/test_models.py
git commit -m "feat(models): SQLModel entities for setting/provider/model/usage"
```

---

## Task 4: Alembic wired to SQLModel metadata

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/script.py.mako`
- Create: `backend/migrations/versions/` (empty dir)
- Create: `backend/tests/test_migration.py`
- Modify: `backend/app/main.py` (run `alembic upgrade head` on startup)

**Interfaces:**
- Produces: Alembic config at `backend/alembic.ini`; migrations under `backend/migrations/versions/`; `create_app()` upgrades schema at startup. `SQLModel.metadata.create_all` is now ONLY used by tests, never by the app.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_migration.py`:
```python
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _cfg(db_path: Path) -> Config:
    c = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    c.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    c.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return c


def test_upgrade_creates_all_tables(tmp_path):
    cfg = _cfg(tmp_path / "mig.sqlite")
    command.upgrade(cfg, "head")
    eng = create_engine(f"sqlite:///{tmp_path / 'mig.sqlite'}")
    names = set(inspect(eng).get_table_names())
    for t in ["setting", "provider", "model", "tokenusage", "tokenusagedaily"]:
        assert t in names, f"missing table {t}"


def test_downgrade_clean(tmp_path):
    cfg = _cfg(tmp_path / "mig.sqlite")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    eng = create_engine(f"sqlite:///{tmp_path / 'mig.sqlite'}")
    names = set(inspect(eng).get_table_names())
    assert {"setting", "provider", "model"}.isdisjoint(names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_migration.py -q`
Expected: FAIL — no `alembic.ini` / no migration revisions yet.

- [ ] **Step 3: Write alembic.ini**

`backend/alembic.ini`:
```ini
[alembic]
script_location = migrations
sqlalchemy.url = sqlite:///data/papermind.sqlite
[loggers]
keys = root
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 4: Write migrations/env.py**

`backend/migrations/env.py`:
```python
from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import app.models  # noqa: F401  ensures all tables register on metadata
from app.config import get_settings

config = context.config

# Use the app's resolved DB path unless alembic.ini overrides (tests set sqlalchemy.url).
if not config.get_main_option("sqlalchemy.url"):
    settings = get_settings()
    config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.resolved_db_path}")

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,  # SQLite: batch mode for ALTERs
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`backend/migrations/script.py.mako` (standard Alembic template):
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 5: Generate the initial migration**

Run:
```bash
cd backend
.venv/Scripts/python -m alembic revision --autogenerate -m "initial schema"
```
Expected: a file appears under `migrations/versions/` containing `op.create_table("setting")`, `"provider"`, `"model"`, `"tokenusage"`, `"tokenusagedaily"`. Open it and verify all five `create_table` calls are present. If autogenerate produced unexpected drops, delete the file and re-run after confirming `app.models` imports cleanly.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_migration.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Wire startup migration into create_app()**

Modify `backend/app/main.py` — replace its body with:
```python
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.health import router as health_router
from app.logging_setup import configure_logging


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    here = Path(__file__).resolve().parent.parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    from app.config import get_settings
    settings = get_settings()
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.resolved_db_path}")
    command.upgrade(cfg, "head")


def create_app() -> FastAPI:
    configure_logging()
    _run_migrations()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="PaperMind", lifespan=lifespan)
    app.include_router(health_router, prefix="/api")
    return app
```

- [ ] **Step 8: Run full suite + manual smoke**

Run:
```bash
cd backend
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -c "from app.main import create_app; create_app(); print('migrated ok')"
```
Expected: all tests pass; smoke prints `migrated ok` and `data/papermind.sqlite` exists with all tables.

- [ ] **Step 9: Commit**

```bash
git add backend/alembic.ini backend/migrations backend/app/main.py backend/tests/test_migration.py
git commit -m "feat(db): Alembic wired to SQLModel metadata, startup migration"
```

---

## Task 5: Encryption (Fernet + master key)

**Files:**
- Create: `backend/app/security/__init__.py` (empty)
- Create: `backend/app/security/master_key.py`
- Create: `backend/app/security/crypto.py`
- Create: `backend/tests/test_crypto.py`

**Interfaces:**
- Produces: `load_or_create_master_key(path: Path) -> bytes`; `Crypto(key: bytes)` with `.encrypt(plaintext: str) -> str` and `.decrypt(token: str) -> str`; `get_crypto()` dep that builds a Crypto from the resolved master key path.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_crypto.py`:
```python
from pathlib import Path

from app.security.master_key import load_or_create_master_key
from app.security.crypto import Crypto


def test_master_key_is_stable(tmp_path):
    p = tmp_path / "mk"
    k1 = load_or_create_master_key(p)
    k2 = load_or_create_master_key(p)
    assert k1 == k2
    assert p.exists()


def test_encrypt_decrypt_roundtrip(tmp_path):
    key = load_or_create_master_key(tmp_path / "mk")
    c = Crypto(key)
    token = c.encrypt("sk-secret-123")
    assert token != "sk-secret-123"
    assert c.decrypt(token) == "sk-secret-123"


def test_distinct_keys_yield_distinct_ciphertext(tmp_path):
    a = Crypto(load_or_create_master_key(tmp_path / "a"))
    b = Crypto(load_or_create_master_key(tmp_path / "b"))
    assert a.encrypt("x") != b.encrypt("x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_crypto.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.security'`.

- [ ] **Step 3: Write master_key + crypto**

`backend/app/security/master_key.py`:
```python
from pathlib import Path

from cryptography.fernet import Fernet


def load_or_create_master_key(path: Path) -> bytes:
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    return key
```

`backend/app/security/crypto.py`:
```python
from cryptography.fernet import Fernet


class Crypto:
    def __init__(self, key: bytes) -> None:
        self._f = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._f.decrypt(token.encode("ascii")).decode("utf-8")


def get_crypto() -> Crypto:
    from app.config import get_settings
    from app.security.master_key import load_or_create_master_key

    settings = get_settings()
    key = load_or_create_master_key(settings.resolved_master_key_path)
    return Crypto(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_crypto.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/security backend/tests/test_crypto.py
git commit -m "feat(security): Fernet encryption + machine-local master key"
```

---

## Task 6: Provider routing (type → LiteLLM call args)

**Files:**
- Create: `backend/app/providers/__init__.py` (empty)
- Create: `backend/app/providers/routing.py`
- Create: `backend/tests/test_routing.py`

**Interfaces:**
- Produces: `route_completion(provider_type: str, model_id: str, base_url: str | None) -> CompletionRoute` where `CompletionRoute` is a dataclass `{litellm_model: str, api_base: str | None, call: str}` with `call` ∈ `{"completion", "responses"}`. Consumes nothing.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_routing.py`:
```python
import pytest

from app.providers.routing import route_completion


def test_openai_chat():
    r = route_completion("openai_chat", "gpt-4o", None)
    assert r.litellm_model == "openai/gpt-4o"
    assert r.api_base is None
    assert r.call == "completion"


def test_openai_compat_uses_base_url():
    r = route_completion("openai_compat", "deepseek-chat", "https://api.deepseek.com/v1")
    assert r.litellm_model == "openai/deepseek-chat"
    assert r.api_base == "https://api.deepseek.com/v1"
    assert r.call == "completion"


def test_anthropic():
    r = route_completion("anthropic", "claude-opus-4-8", None)
    assert r.litellm_model == "anthropic/claude-opus-4-8"
    assert r.call == "completion"


def test_openai_responses():
    r = route_completion("openai_responses", "gpt-4o", None)
    assert r.call == "responses"


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        route_completion("weird", "x", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_routing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.providers.routing'`.

- [ ] **Step 3: Write routing**

`backend/app/providers/routing.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CompletionRoute:
    litellm_model: str
    api_base: str | None
    call: str  # "completion" | "responses"


def route_completion(provider_type: str, model_id: str, base_url: str | None) -> CompletionRoute:
    if provider_type == "openai_chat":
        return CompletionRoute(f"openai/{model_id}", None, "completion")
    if provider_type == "openai_compat":
        if not base_url:
            raise ValueError("openai_compat provider requires base_url")
        return CompletionRoute(f"openai/{model_id}", base_url, "completion")
    if provider_type == "anthropic":
        return CompletionRoute(f"anthropic/{model_id}", None, "completion")
    if provider_type == "openai_responses":
        return CompletionRoute(f"openai/{model_id}", None, "responses")
    raise ValueError(f"unknown provider type: {provider_type}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_routing.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/routing.py backend/tests/test_routing.py
git commit -m "feat(providers): routing for openai_chat/responses/anthropic/compat"
```

---

## Task 7: ProviderClient — LiteLLM complete() + list_models() + token recording

**Files:**
- Create: `backend/app/providers/client.py`
- Create: `backend/tests/test_provider_client.py`

**Interfaces:**
- Consumes: `route_completion` (Task 6); `Provider` model; `Crypto.decrypt`; `get_session`.
- Produces:
  - `@dataclass CompletionResult { content: str, prompt_tokens: int, completion_tokens: int, total_tokens: int }`
  - `@dataclass ModelInfo { model_id: str, display_name: str | None, context_window: int | None }`
  - `class ProviderClient`:
    - `complete(provider: Provider, model_id: str, messages: list[dict], request_kind: str, ref_id: str | None = None) -> CompletionResult`
    - `list_models(provider: Provider) -> list[ModelInfo]`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_provider_client.py`:
```python
from datetime import date
from unittest.mock import MagicMock

import httpx
import respx
from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Provider, TokenUsage
from app.providers.client import ProviderClient, CompletionResult, ModelInfo
from app.security.crypto import Crypto


def _fake_litellm_completion(**kwargs):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="hello world"))]
    resp.usage = MagicMock(prompt_tokens=12, completion_tokens=8, total_tokens=20)
    return resp


def test_complete_records_usage(tmp_path, monkeypatch):
    eng = make_engine(tmp_path / "c.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(__import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key())

    monkeypatch.setattr("app.providers.client.litellm.completion", _fake_litellm_completion)

    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    provider = Provider(id=1, name="oai", type="openai_chat", base_url=None, api_key_encrypted=crypto.encrypt("sk-x"))

    result = client.complete(provider, "gpt-4o", [{"role": "user", "content": "hi"}], request_kind="chat")
    assert isinstance(result, CompletionResult)
    assert result.content == "hello world"
    assert result.total_tokens == 20

    with Session(eng) as s:
        rows = s.exec(select(TokenUsage)).all()
        assert len(rows) == 1
        assert rows[0].total_tokens == 20
        assert rows[0].request_kind == "chat"
        assert rows[0].model == "gpt-4o"


@respx.mock
def test_list_models_openai_compat(tmp_path):
    eng = make_engine(tmp_path / "c.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(__import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key())
    respx.get("https://api.deepseek.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})
    )
    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    provider = Provider(id=1, name="ds", type="openai_compat", base_url="https://api.deepseek.com/v1",
                        api_key_encrypted=crypto.encrypt("sk-x"))
    models = client.list_models(provider)
    assert {m.model_id for m in models} == {"deepseek-chat", "deepseek-reasoner"}
    assert all(isinstance(m, ModelInfo) for m in models)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_provider_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.providers.client'`.

- [ ] **Step 3: Write ProviderClient**

`backend/app/providers/client.py`:
```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
import litellm
from sqlmodel import Session

from app.models import Provider, TokenUsage
from app.providers.routing import route_completion
from app.security.crypto import Crypto


@dataclass
class CompletionResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ModelInfo:
    model_id: str
    display_name: str | None = None
    context_window: int | None = None


class ProviderClient:
    def __init__(self, session_factory: Callable[[], Session], crypto: Crypto) -> None:
        self._session_factory = session_factory
        self._crypto = crypto

    def _api_key(self, provider: Provider) -> str | None:
        if not provider.api_key_encrypted:
            return None
        return self._crypto.decrypt(provider.api_key_encrypted)

    def complete(
        self,
        provider: Provider,
        model_id: str,
        messages: list[dict[str, Any]],
        request_kind: str,
        ref_id: str | None = None,
    ) -> CompletionResult:
        route = route_completion(provider.type, model_id, provider.base_url)
        kwargs: dict[str, Any] = {
            "model": route.litellm_model,
            "messages": messages,
            "api_key": self._api_key(provider),
        }
        if route.api_base:
            kwargs["api_base"] = route.api_base

        if route.call == "responses":
            # LiteLLM exposes the Responses API via litellm.responses().
            resp = litellm.responses(**kwargs)
            content = getattr(resp, "output_text", None) or ""
            usage = getattr(resp, "usage", None)
        else:
            resp = litellm.completion(**kwargs)
            content = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)

        prompt_t = getattr(usage, "prompt_tokens", 0) or 0
        completion_t = getattr(usage, "completion_tokens", 0) or 0
        total_t = getattr(usage, "total_tokens", prompt_t + completion_t) or (prompt_t + completion_t)

        self._record_usage(provider, model_id, request_kind, ref_id, prompt_t, completion_t, total_t)
        return CompletionResult(content, prompt_t, completion_t, total_t)

    def _record_usage(
        self, provider: Provider, model_id: str, request_kind: str,
        ref_id: str | None, prompt_t: int, completion_t: int, total_t: int,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                TokenUsage(
                    provider_id=provider.id,
                    model=model_id,
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                    request_kind=request_kind,
                    ref_id=ref_id,
                    day=date.today(),
                )
            )
            session.commit()

    def list_models(self, provider: Provider) -> list[ModelInfo]:
        url, headers = self._models_endpoint(provider)
        data = httpx.get(url, headers=headers, timeout=30.0).json()
        raw = data.get("data", data) if isinstance(data, dict) else data
        out: list[ModelInfo] = []
        for item in raw or []:
            mid = item.get("id") or item.get("model") or item.get("name")
            if not mid:
                continue
            out.append(ModelInfo(model_id=mid, display_name=item.get("id")))
        return out

    def _models_endpoint(self, provider: Provider) -> tuple[str, dict[str, str]]:
        key = self._api_key(provider)
        if provider.type in {"openai_chat", "openai_responses", "openai_compat"}:
            base = (provider.base_url or "https://api.openai.com/v1").rstrip("/")
            return f"{base}/models", {"Authorization": f"Bearer {key}"} if key else {}
        if provider.type == "anthropic":
            return "https://api.anthropic.com/v1/models", {
                "x-api-key": key or "",
                "anthropic-version": "2023-06-01",
            }
        raise ValueError(f"no models endpoint for type {provider.type}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_provider_client.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/client.py backend/tests/test_provider_client.py
git commit -m "feat(providers): LiteLLM ProviderClient with token recording + model listing"
```

---

## Task 8: Settings API (CRUD)

**Files:**
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/settings_api.py`
- Modify: `backend/app/main.py` (mount settings router)
- Create: `backend/tests/test_settings_api.py`

**Interfaces:**
- Consumes: `get_session` (Task 2), `Setting` (Task 3).
- Produces: REST endpoints under `/api/settings`:
  - `GET /api/settings` → `{key: value, ...}`
  - `GET /api/settings/{key}` → `{"key": k, "value": v}` (404 if missing)
  - `PUT /api/settings/{key}` body `{"value": "..."}` → upsert, returns the setting
  - `DELETE /api/settings/{key}` → 204

- [ ] **Step 1: Write the failing test**

`backend/tests/test_settings_api.py`:
```python
def test_settings_crud(client):
    assert client.get("/api/settings").json() == {}

    put = client.put("/api/settings/theme", json={"value": "dark"})
    assert put.status_code == 200
    assert put.json() == {"key": "theme", "value": "dark"}

    assert client.get("/api/settings/theme").json()["value"] == "dark"

    put2 = client.put("/api/settings/theme", json={"value": "light"})
    assert put2.json()["value"] == "light"

    missing = client.get("/api/settings/nope")
    assert missing.status_code == 404

    deleted = client.delete("/api/settings/theme")
    assert deleted.status_code == 204
    assert client.get("/api/settings/theme").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_settings_api.py -q`
Expected: FAIL — 404 from unknown route (router not mounted).

- [ ] **Step 3: Write deps + settings router**

`backend/app/api/deps.py`:
```python
from collections.abc import Iterator
from sqlmodel import Session

from app.db.engine import get_session as _get_session


def get_session() -> Iterator[Session]:
    yield from _get_session()
```

`backend/app/api/settings_api.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Setting

router = APIRouter()


class SettingIn(BaseModel):
    value: str | None = None


@router.get("/settings")
def list_settings(session: Session = Depends(get_session)) -> dict:
    rows = session.exec(select(Setting)).all()
    return {r.key: r.value for r in rows}


@router.get("/settings/{key}")
def get_setting(key: str, session: Session = Depends(get_session)) -> dict:
    row = session.get(Setting, key)
    if row is None:
        raise HTTPException(404, "setting not found")
    return {"key": row.key, "value": row.value}


@router.put("/settings/{key}")
def upsert_setting(key: str, body: SettingIn, session: Session = Depends(get_session)) -> dict:
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=body.value)
    else:
        row.value = body.value
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"key": row.key, "value": row.value}


@router.delete("/settings/{key}", status_code=204)
def delete_setting(key: str, session: Session = Depends(get_session)) -> None:
    row = session.get(Setting, key)
    if row is not None:
        session.delete(row)
        session.commit()
```

- [ ] **Step 4: Mount router in create_app()**

In `backend/app/main.py`, add to `create_app()` alongside the health router:
```python
from app.api.settings_api import router as settings_router
# ... inside create_app(), after health:
app.include_router(settings_router, prefix="/api")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_settings_api.py -q`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/deps.py backend/app/api/settings_api.py backend/app/main.py backend/tests/test_settings_api.py
git commit -m "feat(api): settings key-value CRUD"
```

---

## Task 9: Providers API (CRUD with encryption + models refresh)

**Files:**
- Create: `backend/app/api/providers_api.py`
- Modify: `backend/app/main.py` (mount providers router)
- Create: `backend/tests/test_providers_api.py`

**Interfaces:**
- Consumes: `get_session`, `get_crypto`, `ProviderClient` (Task 7).
- Produces: REST under `/api/providers`:
  - `GET /api/providers` → list (api_key NEVER returned; field omitted)
  - `POST /api/providers` body `{name, type, base_url?, api_key?, enabled?}` → encrypts key, returns provider (no key)
  - `PATCH /api/providers/{id}` body partial → updates; if `api_key` supplied, re-encrypt
  - `DELETE /api/providers/{id}` → 204 (cascades models via FK ON DELETE — set in migration)
  - `POST /api/providers/{id}/models/refresh` → calls `ProviderClient.list_models`, upserts `Model` rows, returns count

- [ ] **Step 1: Write the failing test**

`backend/tests/test_providers_api.py`:
```python
from unittest.mock import patch


def test_create_provider_encrypts_key_and_hides_it(client):
    res = client.post("/api/providers", json={
        "name": "deepseek", "type": "openai_compat",
        "base_url": "https://api.deepseek.com/v1", "api_key": "sk-secret",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "deepseek"
    assert "api_key" not in body
    assert "api_key_encrypted" not in body
    assert body["id"] is not None


def test_list_hides_keys(client):
    client.post("/api/providers", json={"name": "a", "type": "openai_chat", "api_key": "sk"})
    lst = client.get("/api/providers").json()
    assert lst and "api_key" not in lst[0]


def test_refresh_models_upserts(client):
    pid = client.post("/api/providers", json={
        "name": "ds", "type": "openai_compat",
        "base_url": "https://api.deepseek.com/v1", "api_key": "sk",
    }).json()["id"]

    fake_models = [
        type("M", (), {"model_id": "deepseek-chat", "display_name": "deepseek-chat", "context_window": None})(),
        type("M", (), {"model_id": "deepseek-reasoner", "display_name": "deepseek-reasoner", "context_window": None})(),
    ]
    with patch("app.api.providers_api.ProviderClient.list_models", return_value=fake_models):
        res = client.post(f"/api/providers/{pid}/models/refresh")
    assert res.status_code == 200
    assert res.json()["count"] == 2

    models = client.get(f"/api/providers/{pid}/models").json()
    assert {m["model_id"] for m in models} == {"deepseek-chat", "deepseek-reasoner"}

    # second refresh replaces, not duplicates
    with patch("app.api.providers_api.ProviderClient.list_models", return_value=fake_models):
        client.post(f"/api/providers/{pid}/models/refresh")
    models = client.get(f"/api/providers/{pid}/models").json()
    assert len(models) == 2


def test_delete_provider(client):
    pid = client.post("/api/providers", json={"name": "x", "type": "openai_chat"}).json()["id"]
    assert client.delete(f"/api/providers/{pid}").status_code == 204
    assert client.get("/api/providers").json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_providers_api.py -q`
Expected: FAIL — routes unknown.

- [ ] **Step 3: Write providers router**

`backend/app/api/providers_api.py`:
```python
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Provider, Model
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto

router = APIRouter()


class ProviderIn(BaseModel):
    name: str
    type: str
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True


class ProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None


def _public(p: Provider) -> dict:
    return {
        "id": p.id, "name": p.name, "type": p.type,
        "base_url": p.base_url, "enabled": p.enabled,
    }


def _client(session: Session) -> ProviderClient:
    return ProviderClient(session_factory=lambda: session, crypto=get_crypto())


@router.get("/providers")
def list_providers(session: Session = Depends(get_session)) -> list[dict]:
    return [_public(p) for p in session.exec(select(Provider)).all()]


@router.post("/providers")
def create_provider(body: ProviderIn, session: Session = Depends(get_session)) -> dict:
    crypto = get_crypto()
    p = Provider(
        name=body.name, type=body.type, base_url=body.base_url, enabled=body.enabled,
        api_key_encrypted=crypto.encrypt(body.api_key) if body.api_key else None,
    )
    session.add(p); session.commit(); session.refresh(p)
    return _public(p)


@router.patch("/providers/{pid}")
def patch_provider(pid: int, body: ProviderPatch, session: Session = Depends(get_session)) -> dict:
    p = session.get(Provider, pid)
    if p is None:
        raise HTTPException(404, "provider not found")
    if body.name is not None:
        p.name = body.name
    if body.base_url is not None:
        p.base_url = body.base_url
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.api_key is not None:
        p.api_key_encrypted = get_crypto().encrypt(body.api_key)
    p.updated_at = datetime.utcnow()
    session.add(p); session.commit(); session.refresh(p)
    return _public(p)


@router.delete("/providers/{pid}", status_code=204)
def delete_provider(pid: int, session: Session = Depends(get_session)) -> None:
    p = session.get(Provider, pid)
    if p is not None:
        session.delete(p)
        session.commit()


@router.post("/providers/{pid}/models/refresh")
def refresh_models(pid: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Provider, pid)
    if p is None:
        raise HTTPException(404, "provider not found")
    fetched = _client(session).list_models(p)
    # Replace existing manual-fetched rows for this provider.
    for existing in session.exec(select(Model).where(Model.provider_id == pid)).all():
        session.delete(existing)
    from datetime import datetime
    now = datetime.utcnow()
    for m in fetched:
        session.add(Model(
            provider_id=pid, model_id=m.model_id, display_name=m.display_name,
            context_window=m.context_window, fetched_at=now, is_manual=False,
        ))
    session.commit()
    return {"count": len(fetched)}


@router.get("/providers/{pid}/models")
def list_provider_models(pid: int, session: Session = Depends(get_session)) -> list[dict]:
    return [
        {"id": m.id, "model_id": m.model_id, "display_name": m.display_name,
         "context_window": m.context_window, "role_default": m.role_default}
        for m in session.exec(select(Model).where(Model.provider_id == pid)).all()
    ]
```

- [ ] **Step 4: Add ON DELETE cascade to provider→model in migration**

Generate a new migration:
```bash
cd backend
.venv/Scripts/python -m alembic revision --autogenerate -m "cascade delete provider model"
```
If autogenerate produces nothing meaningful, write it manually in the new file's `upgrade()`:
```python
def upgrade() -> None:
    op.drop_constraint("model_provider_id_fkey", "model", type_="foreignkey")
    op.create_foreign_key("model_provider_id_fkey", "model", "provider",
                          ["provider_id"], ["id"], ondelete="CASCADE")
```
and a matching reverse in `downgrade()`. Then `alembic upgrade head`.

- [ ] **Step 5: Mount router**

In `backend/app/main.py`:
```python
from app.api.providers_api import router as providers_router
# inside create_app():
app.include_router(providers_router, prefix="/api")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_providers_api.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/providers_api.py backend/app/main.py backend/migrations backend/tests/test_providers_api.py
git commit -m "feat(api): providers CRUD with encrypted keys + model refresh"
```

---

## Task 10: Models API (global list) + role assignment

**Files:**
- Create: `backend/app/api/models_api.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_models_api.py`

**Interfaces:**
- Consumes: `get_session`, `Model`, `Provider`.
- Produces:
  - `GET /api/models` → all models joined with provider name
  - `PATCH /api/models/{id}` body `{role_default?: str, display_name?: str}` → update

- [ ] **Step 1: Write the failing test**

`backend/tests/test_models_api.py`:
```python
def test_models_list_and_role(client):
    pid = client.post("/api/providers", json={"name": "oai", "type": "openai_chat"}).json()["id"]
    # inject a model directly via API refresh (reuse providers refresh) is heavier;
    # use DB via the app's session instead.
    from app.db.engine import get_engine
    from app.models import Model
    from sqlmodel import Session
    with Session(get_engine()) as s:
        s.add(Model(provider_id=pid, model_id="gpt-4o", display_name="GPT-4o"))
        s.commit()

    models = client.get("/api/models").json()
    assert len(models) == 1
    assert models[0]["model_id"] == "gpt-4o"
    assert models[0]["provider_name"] == "oai"

    mid = models[0]["id"]
    patched = client.patch(f"/api/models/{mid}", json={"role_default": "chat"})
    assert patched.json()["role_default"] == "chat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models_api.py -q`
Expected: FAIL — unknown route.

- [ ] **Step 3: Write models router**

`backend/app/api/models_api.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Model, Provider

router = APIRouter()


class ModelPatch(BaseModel):
    role_default: str | None = None
    display_name: str | None = None


@router.get("/models")
def list_models(session: Session = Depends(get_session)) -> list[dict]:
    out = []
    for m in session.exec(select(Model)).all():
        p = session.get(Provider, m.provider_id)
        out.append({
            "id": m.id, "model_id": m.model_id, "display_name": m.display_name,
            "context_window": m.context_window, "role_default": m.role_default,
            "provider_id": m.provider_id, "provider_name": p.name if p else None,
        })
    return out


@router.patch("/models/{mid}")
def patch_model(mid: int, body: ModelPatch, session: Session = Depends(get_session)) -> dict:
    m = session.get(Model, mid)
    if m is None:
        raise HTTPException(404, "model not found")
    if body.role_default is not None:
        m.role_default = body.role_default
    if body.display_name is not None:
        m.display_name = body.display_name
    session.add(m); session.commit(); session.refresh(m)
    return {"id": m.id, "role_default": m.role_default, "display_name": m.display_name}
```

- [ ] **Step 4: Mount router**

In `backend/app/main.py`:
```python
from app.api.models_api import router as models_router
# inside create_app():
app.include_router(models_router, prefix="/api")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models_api.py -q`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/models_api.py backend/app/main.py backend/tests/test_models_api.py
git commit -m "feat(api): global models list + role assignment"
```

---

## Task 11: Usage API (token stats aggregates)

**Files:**
- Create: `backend/app/api/usage_api.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_usage_api.py`

**Interfaces:**
- Consumes: `get_session`, `TokenUsage`.
- Produces: `GET /api/usage?days=30` → `{"total_tokens": int, "by_kind": {kind: tokens}, "by_model": {model: tokens}, "by_day": [{"day": str, "tokens": int}]}` over the last N days (default 30).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_usage_api.py`:
```python
from datetime import date, timedelta
from app.db.engine import get_engine
from app.models import TokenUsage, Provider
from sqlmodel import Session


def _seed(client):
    with Session(get_engine()) as s:
        s.add(Provider(name="oai", type="openai_chat"))
        s.commit()
        s.refresh(s.exec(__import__("sqlmodel").select(Provider)).first())
        p = s.exec(__import__("sqlmodel").select(Provider)).first()
        today = date.today()
        s.add(TokenUsage(provider_id=p.id, model="gpt-4o", prompt_tokens=100, completion_tokens=50,
                         total_tokens=150, request_kind="chat", day=today))
        s.add(TokenUsage(provider_id=p.id, model="gpt-4o", prompt_tokens=40, completion_tokens=10,
                         total_tokens=50, request_kind="ingest", day=today))
        s.commit()


def test_usage_aggregates(client):
    _seed(client)
    res = client.get("/api/usage?days=30").json()
    assert res["total_tokens"] == 200
    assert res["by_kind"]["chat"] == 150
    assert res["by_kind"]["ingest"] == 50
    assert res["by_model"]["gpt-4o"] == 200
    assert any(d["tokens"] == 200 for d in res["by_day"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_usage_api.py -q`
Expected: FAIL — unknown route.

- [ ] **Step 3: Write usage router**

`backend/app/api/usage_api.py`:
```python
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import TokenUsage

router = APIRouter()


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), session: Session = Depends(get_session)) -> dict:
    since = date.today() - timedelta(days=days - 1)
    rows = session.exec(select(TokenUsage).where(TokenUsage.day >= since)).all()

    total = 0
    by_kind: dict[str, int] = defaultdict(int)
    by_model: dict[str, int] = defaultdict(int)
    by_day: dict[str, int] = defaultdict(int)

    for r in rows:
        total += r.total_tokens
        by_kind[r.request_kind] += r.total_tokens
        by_model[r.model] += r.total_tokens
        by_day[r.day.isoformat()] += r.total_tokens

    return {
        "total_tokens": total,
        "by_kind": dict(by_kind),
        "by_model": dict(by_model),
        "by_day": [{"day": d, "tokens": t} for d, t in sorted(by_day.items())],
    }
```

- [ ] **Step 4: Mount router**

In `backend/app/main.py`:
```python
from app.api.usage_api import router as usage_router
# inside create_app():
app.include_router(usage_router, prefix="/api")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_usage_api.py -q`
Expected: PASS (1 passed).

- [ ] **Step 6: Run full suite + smoke-run the server**

Run:
```bash
cd backend
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000 &
sleep 2
.venv/Scripts/python -c "import httpx; print(httpx.get('http://127.0.0.1:8000/api/health').json())"
# stop the server (Ctrl-C or kill)
```
Expected: full suite green (all tasks' tests); health smoke prints `{'status': 'ok'}`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/usage_api.py backend/app/main.py backend/tests/test_usage_api.py
git commit -m "feat(api): token usage aggregates endpoint"
```

---

## Self-Review

Run this checklist against the spec after the plan is written.

**1. Spec coverage (P0a scope):**
- Backend skeleton → Task 1. ✅
- SQLite + WAL + sqlite-vec loader → Task 2. ✅
- Alembic → Task 4. ✅
- Core models (Setting/Provider/Model/TokenUsage) → Task 3. ✅ (Paper/Concept/etc. belong to P1+, intentionally out of scope)
- Provider layer (LiteLLM, 4 types, model list fetch) → Tasks 6, 7. ✅
- Encryption (Fernet) → Task 5. ✅
- Settings API → Task 8. ✅
- Providers/Models API → Tasks 9, 10. ✅
- Token usage recording + stats → Tasks 7 (recording), 11 (stats). ✅
- Model routing by role → Task 10 PATCH `role_default` (the role→task wiring in the agent is P2). ✅ for P0a
- Frontend scaffold / settings UI / one-command launch → **P0b (next plan)**, intentionally deferred.

**2. Placeholder scan:** No TBD/TODO/"add error handling". Every code step shows full code. Verified.

**3. Type consistency:**
- `route_completion` returns `CompletionRoute(litellm_model, api_base, call)` — consumed identically in Task 7. ✅
- `ProviderClient.__init__(session_factory, crypto)` signature matches both Task 7 tests and Task 9's `_client()`. ✅
- `ModelInfo(model_id, display_name, context_window)` used in Task 7 list_models and Task 9 refresh. ✅
- `CompletionResult` fields match the Task 7 test assertions. ✅
- `_public(provider)` omits `api_key`/`api_key_encrypted` consistently across Task 9 list/create/patch. ✅
- `get_session` is provided by `app.api.deps.get_session` (Task 8) and used by all later routers — single source. ✅

No gaps for the P0a scope. Frontend + launch explicitly tracked as P0b.
