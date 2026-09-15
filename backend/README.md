# PaperMind Backend

FastAPI service: multi-provider LLM access, encrypted API-key storage, paper
ingestion/analysis, reading workspace, RAG chat with an agent tool loop,
thesis workspace with chapter drafts, and the settings/providers/models/usage
APIs. Serves the built frontend in production.

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

## Modules

| Area | Where | Notes |
|---|---|---|
| Health / settings / providers / models / usage | `app/api/{health,settings_api,providers_api,models_api,usage_api}.py` | Role assignment: one `chat` LLM (对话/总结/抽取共用) + one `embedding` model |
| Ingestion & analysis | `app/ingestion/`, `app/api/papers_api.py` | arXiv / BibTeX / RIS / PDF / manual / external queueing; auto AI analysis when an LLM is configured |
| Reading workspace | `app/reading/`, `app/api/reading_api.py` | notes / excerpts / review matrix / reading states / recently-read |
| RAG + agent chat | `app/rag/`, `app/agent/`, `app/api/chat_api.py` | SSE streaming, agent tools (`search_library`, `search_research_notes`, …), per-message paper context |
| Thesis workspace | `app/thesis/`, `app/api/thesis_api.py` | projects/chapters/links, chapter drafts, markdown & bibtex exports |
| Knowledge & discovery | `app/knowledge/`, `app/api/{graph_api,suggestions_api,radar_api}.py` | OpenAlex related papers, citation matching, suggestions, arXiv radar |
| Ideas / experiments / reports | `app/idea/`, `app/experiment/`, `app/reports/` | research loop artifacts |

## Provider types

`openai_chat`, `openai_responses` (Responses API), `anthropic`, `openai_compat`
(custom base_url: DeepSeek / 智谱 / Moonshot / SiliconFlow / Ollama / …).
`openai_compat` requires `base_url`. All go through LiteLLM; every completion
records a `TokenUsage` row.
