# PaperMind Reading Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Reading Workspace so each paper can store human reading progress, notes, excerpts, and literature-review matrix fields.

**Architecture:** Add SQLModel reading tables plus an Alembic migration, then expose them through a focused `app.reading.service` and thin FastAPI routes. Integrate reading summaries into paper listing, include reading data in JSON export, and add a compact Reading Workspace plus matrix view to the existing Library UI.

**Tech Stack:** Python 3.14 runtime in the current venv, FastAPI, SQLModel, Alembic, SQLite WAL, pytest, React, TypeScript, Vite.

---

## Baseline

- Current branch: `feat/p0a-backend-foundation`, not main/master.
- Worktree already contains uncommitted Phase 1 archive/export work and earlier validation fixes.
- Do not revert unrelated or previous-phase changes.

---

## File Structure

Create:

- `backend/app/models/reading.py`: `PaperReadingState`, `PaperNote`, `PaperExcerpt`, `ReviewMatrixEntry`.
- `backend/app/reading/__init__.py`: service exports.
- `backend/app/reading/service.py`: business rules and serialization.
- `backend/app/api/reading_api.py`: `/api/papers/{id}/reading/*` and `/api/reading/matrix`.
- `backend/migrations/versions/f2a9c1d4e6b8_reading_workspace.py`: new reading tables.
- `backend/tests/test_reading.py`: service/API behavior tests.

Modify:

- `backend/app/models/__init__.py`: import/export reading models.
- `backend/app/main.py`: include reading router.
- `backend/app/api/papers_api.py`: add reading summary to paper list/detail.
- `backend/app/archive/service.py`: include reading data in JSON export.
- `frontend/src/api.ts`: add reading types and API methods.
- `frontend/src/pages/Library.tsx`: show reading chips, filters, detail workspace, and matrix view.

---

## Task 1: Reading Models and Migration

**Files:**
- Create: `backend/app/models/reading.py`
- Create: `backend/migrations/versions/f2a9c1d4e6b8_reading_workspace.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_reading.py`

- [ ] **Step 1: Write the failing model/migration test**

Add a test that imports the reading models, creates rows through `SQLModel.metadata.create_all`, and verifies the Alembic-managed test app can query default workspace later.

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_reading.py::test_reading_models_roundtrip -q`

Expected: FAIL with missing `app.models.reading`.

- [ ] **Step 2: Implement models and migration**

Models:

- `PaperReadingState`: paper_id unique FK, status, priority, rating, relevance, started_at, finished_at, last_read_at, updated_at.
- `PaperNote`: paper_id FK, kind, content, tags_json, created_at, updated_at.
- `PaperExcerpt`: paper_id FK, quote, page, section, locator, note, tags_json, created_at, updated_at.
- `ReviewMatrixEntry`: paper_id unique FK, problem, method, dataset, metrics, results, limitations, novelty, relation_to_thesis, future_work, notes, updated_at.

Migration creates all four tables and indexes from the spec.

- [ ] **Step 3: Verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_reading.py::test_reading_models_roundtrip -q`

Expected: PASS.

---

## Task 2: Reading Service

**Files:**
- Create: `backend/app/reading/__init__.py`
- Create: `backend/app/reading/service.py`
- Test: `backend/tests/test_reading.py`

- [ ] **Step 1: Write failing service tests**

Tests cover:

- default workspace returns unread/normal and empty notes/excerpts/matrix.
- patching status to `reading` fills `started_at` and `last_read_at`.
- patching status to `read` fills `finished_at`.
- invalid status/priority/rating/relevance raises `ValueError`.
- create/patch/delete note.
- create/patch/delete excerpt with positive page validation.
- matrix upsert and global matrix listing.
- soft-deleted paper returns `LookupError`.

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_reading.py -q`

Expected: FAIL because service module is missing.

- [ ] **Step 2: Implement service**

Core functions:

- `get_reading_workspace(session, paper_id)`
- `patch_reading_state(session, paper_id, payload)`
- `upsert_review_matrix(session, paper_id, payload)`
- `create_note(session, paper_id, payload)`
- `patch_note(session, paper_id, note_id, payload)`
- `delete_note(session, paper_id, note_id)`
- `create_excerpt(session, paper_id, payload)`
- `patch_excerpt(session, paper_id, excerpt_id, payload)`
- `delete_excerpt(session, paper_id, excerpt_id)`
- `list_review_matrix(session, status=None, q=None, min_relevance=None, high_priority=False)`
- `reading_summary(session, paper_id)`

Use `ValueError` for validation failures and `LookupError` for missing/soft-deleted papers or wrong ownership.

- [ ] **Step 3: Verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_reading.py -q`

Expected: PASS.

---

## Task 3: Reading API and Paper List Integration

**Files:**
- Create: `backend/app/api/reading_api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/papers_api.py`
- Test: `backend/tests/test_reading.py`

- [ ] **Step 1: Write failing API tests**

Tests cover:

- `GET /api/papers/{id}/reading` default workspace.
- `PATCH /api/papers/{id}/reading/state` updates state.
- `PUT /api/papers/{id}/reading/matrix` upserts matrix.
- note create/patch/delete endpoints.
- excerpt create/patch/delete endpoints.
- `GET /api/reading/matrix` lists non-deleted papers.
- `GET /api/papers` includes a `reading` summary field.

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_reading.py -q`

Expected: FAIL with 404s.

- [ ] **Step 2: Implement route layer and include router**

Map service `LookupError` to 404 and `ValueError` to 422. Keep route functions thin.

- [ ] **Step 3: Add paper reading summaries**

Add `reading` summary to paper list/detail payloads:

```json
{"status":"unread","priority":"normal","rating":null,"relevance":null}
```

- [ ] **Step 4: Verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_reading.py -q`

Expected: PASS.

---

## Task 4: Archive JSON Export Integration

**Files:**
- Modify: `backend/app/archive/service.py`
- Test: `backend/tests/test_archive.py`

- [ ] **Step 1: Write failing archive export test**

Extend archive export tests to seed reading state, note, excerpt, and matrix, then assert `export_json()` includes:

- `reading_states`
- `paper_notes`
- `paper_excerpts`
- `review_matrix_entries`

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_export_json_includes_reading_workspace_data -q`

Expected: FAIL because archive export does not include reading rows yet.

- [ ] **Step 2: Include reading models in export**

Import reading models in `archive/service.py` and append the four collections to `export_json`.

- [ ] **Step 3: Verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_export_json_includes_reading_workspace_data -q`

Expected: PASS.

---

## Task 5: Frontend API and Library UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/Library.tsx`

- [ ] **Step 1: Add frontend API types and methods**

Add:

- `ReadingState`
- `PaperNote`
- `PaperExcerpt`
- `ReviewMatrixEntry`
- `ReadingWorkspace`
- `MatrixRow`

Add methods from the spec.

- [ ] **Step 2: Add Library state**

Add state for:

- detail reading workspace
- active detail tab/section
- note/excerpt draft fields
- matrix view rows and filters
- paper list reading filters

- [ ] **Step 3: Add paper list chips and filters**

Show status, high priority, and relevance. Add filters for status, high priority only, and minimum relevance.

- [ ] **Step 4: Add detail Reading Workspace**

Add compact sections for:

- Overview controls
- Matrix textareas
- Notes create/list/delete
- Excerpts create/list/delete

- [ ] **Step 5: Add Matrix view**

Add a Library toggle between paper list and review matrix. Matrix table shows title, year, status, relevance, problem, method, results, limitations, and relation to thesis.

- [ ] **Step 6: Verify frontend build**

Run: `cd frontend && npm.cmd run build`

Expected: PASS.

---

## Task 6: Full Verification and Smoke Test

**Files:**
- No new files.

- [ ] **Step 1: Run focused backend tests**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_reading.py tests/test_archive.py tests/test_archive_api.py -q`

Expected: PASS.

- [ ] **Step 2: Run full backend suite**

Run: `cd backend && .venv\Scripts\python -m pytest`

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run: `cd frontend && npm.cmd run build`

Expected: PASS.

- [ ] **Step 4: Run HTTP smoke test**

With a temp data dir and TestClient:

- seed one paper
- `PATCH /api/papers/{id}/reading/state`
- create note
- create excerpt
- save matrix
- get workspace
- get matrix list
- export JSON and confirm reading collections are present

Expected: all assertions pass.

