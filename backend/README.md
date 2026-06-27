# PaperMind Backend (P0a — Foundation)

FastAPI service providing multi-provider LLM access, encrypted API-key storage,
and the data/settings/providers/models/usage APIs. This is the foundation
layer; ingestion, agents, graphs, and chat arrive in later phases (P1+).

## Stack

Python ≥ 3.11 · FastAPI · SQLModel (SQLAlchemy 2.0) · SQLite (WAL) · sqlite-vec
· Alembic · LiteLLM · cryptography (Fernet) · pydantic-settings · httpx.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
# .venv/bin/python -m pip install -e ".[dev]"     # macOS/Linux
```

## Run

```bash
.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 8000 --reload
```

On startup the app applies Alembic migrations to the configured SQLite DB and
serves the API under `/api`. Data lives under `data/` (gitignored): the SQLite
DB and the Fernet master key that encrypts API keys at rest.

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `PAPERMIND_DATA_DIR` | `data` | DB + master-key location |
| `PAPERMIND_DB_PATH` | `<data_dir>/papermind.sqlite` | SQLite path |
| `PAPERMIND_MASTER_KEY_PATH` | `<data_dir>/master.key` | Fernet master key (auto-generated) |

`LITELLM_LOCAL_MODEL_COST_MAP=True` is set in code so startup has no network
dependency (avoids litellm's remote cost-map fetch).

## Test

```bash
.venv/Scripts/python -m pytest
```

Tests use an isolated temp DB per case (path-keyed engine cache) and a
project-local pytest basetemp, so no shared state and no reliance on the
system temp dir.

## API (P0a)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness |
| GET/PUT/DELETE | `/api/settings[/{key}]` | App settings (key-value) |
| GET/POST/PATCH/DELETE | `/api/providers[/{id}]` | Provider CRUD (keys encrypted) |
| POST | `/api/providers/{id}/models/refresh` | Fetch model list from provider → DB |
| GET | `/api/providers/{id}/models` | Models for a provider |
| GET/PATCH | `/api/models[/{id}]` | All models / role assignment |
| GET | `/api/usage?days=N` | Token-usage aggregates |

## Provider types

`openai_chat`, `openai_responses` (Responses API), `anthropic`, `openai_compat`
(custom base_url: DeepSeek / 智谱 / Moonshot / SiliconFlow / Ollama / …).
`openai_compat` requires `base_url`. All go through LiteLLM; every completion
records a `TokenUsage` row.
