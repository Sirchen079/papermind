# PaperMind Archive and Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Data Safety phase that lets a master's student inspect, back up, download, and export the local PaperMind library without exposing secrets in shareable exports.

**Architecture:** Add a focused `app.archive` backend module that owns filesystem traversal, SQLite snapshotting, manifest hashing, backup zip creation, and export formatting. FastAPI routes stay thin and only translate service results into JSON or downloadable responses. The Settings page gains a compact Data Safety section that calls these endpoints.

**Tech Stack:** Python 3.14 runtime in the current venv, FastAPI, SQLModel, SQLite WAL, pytest, React, TypeScript, Vite.

---

## Baseline Evidence

- `backend/.venv/Scripts/python -m pytest`: 155 passed on 2026-06-29 before archive implementation.
- `frontend/npm.cmd run build`: passed on 2026-06-29 before archive implementation.
- Current branch: `feat/p0a-backend-foundation`.

---

## File Structure

Create:

- `backend/app/archive/__init__.py`: exports service functions.
- `backend/app/archive/bibtex.py`: citekey generation and BibTeX escaping/formatting.
- `backend/app/archive/service.py`: archive status, backup creation/listing, safe path resolution, JSON export, BibTeX export.
- `backend/app/api/archive_api.py`: `/api/archive/*` routes.
- `backend/tests/test_archive.py`: service-level tests.
- `backend/tests/test_archive_api.py`: API-level tests.

Modify:

- `backend/app/main.py`: include archive router under `/api`.
- `frontend/src/api.ts`: add archive types and methods.
- `frontend/src/pages/Settings.tsx`: add Data Safety section.

No database migration is needed.

---

## Task 1: Backend Status Service

**Files:**
- Create: `backend/app/archive/__init__.py`
- Create: `backend/app/archive/service.py`
- Test: `backend/tests/test_archive.py`

- [ ] **Step 1: Write failing service test**

Add `backend/tests/test_archive.py` with a test that seeds one paper, one summary, one concept link, one chunk, and one provider, creates a PDF and `master.key`, then calls `archive_status(session)`.

```python
def test_archive_status_reports_data_health(env):
    from sqlmodel import Session

    from app.archive.service import archive_status
    from app.db.engine import get_engine
    from app.models import Concept, Paper, PaperChunk, PaperConcept, Provider, Summary

    pdf_dir = env / "data" / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
    (env / "master.key").write_bytes(b"secret-key")

    with Session(get_engine()) as session:
        paper = Paper(source="pdf", title="A Test Paper", pdf_path=str(pdf_dir / "paper.pdf"))
        provider = Provider(name="kimi", type="anthropic", api_key_encrypted="encrypted")
        concept = Concept(name="RAG", normalized_key="rag", type="method")
        session.add(paper)
        session.add(provider)
        session.add(concept)
        session.commit()
        session.refresh(paper)
        session.refresh(concept)
        session.add(Summary(paper_id=paper.id, content_json='{"problem":"x"}'))
        session.add(PaperConcept(paper_id=paper.id, concept_id=concept.id))
        session.add(PaperChunk(paper_id=paper.id, ordinal=0, text="chunk", embedding=b"blob"))
        session.commit()

        status = archive_status(session)

    assert status["database_exists"] is True
    assert status["master_key_exists"] is True
    assert status["pdf_count"] == 1
    assert status["paper_count"] == 1
    assert status["summary_count"] == 1
    assert status["concept_count"] == 1
    assert status["chunk_count"] == 1
    assert status["provider_count"] == 1
    assert status["latest_backup"] is None
```

- [ ] **Step 2: Run test to verify RED**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_archive_status_reports_data_health -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.archive'`.

- [ ] **Step 3: Implement minimal status service**

`archive_status(session)` must:

- read paths from `get_settings()`
- count `Paper` where `is_deleted == False`
- count all `Summary`, `Concept`, `PaperChunk`, and `Provider`
- compute PDF count and bytes under `<data_dir>/pdfs`
- return only serializable primitives
- never return API key plaintext or encrypted API key ciphertext

- [ ] **Step 4: Run test to verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_archive_status_reports_data_health -q`

Expected: PASS.

---

## Task 2: Backup Zip Service

**Files:**
- Modify: `backend/app/archive/service.py`
- Test: `backend/tests/test_archive.py`

- [ ] **Step 1: Write failing backup test**

Add `test_create_backup_writes_manifest_sqlite_key_and_pdfs`:

```python
def test_create_backup_writes_manifest_sqlite_key_and_pdfs(env):
    import json
    import zipfile
    from sqlmodel import Session

    from app.archive.service import create_backup
    from app.db.engine import get_engine
    from app.models import Paper

    pdf_dir = env / "data" / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "nested").mkdir()
    (pdf_dir / "nested" / "paper.pdf").write_bytes(b"%PDF-1.4")
    (env / "master.key").write_bytes(b"secret-key")

    with Session(get_engine()) as session:
        session.add(Paper(source="pdf", title="Backup Paper"))
        session.commit()
        backup = create_backup(session)

    assert backup["filename"].startswith("papermind-backup-")
    assert backup["filename"].endswith(".zip")
    assert backup["size_bytes"] > 0

    with zipfile.ZipFile(backup["path"]) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "papermind.sqlite" in names
        assert "master.key" in names
        assert "pdfs/nested/paper.pdf" in names
        manifest = json.loads(zf.read("manifest.json"))

    assert manifest["archive_schema_version"] == 1
    assert manifest["paper_count"] == 1
    assert manifest["master_key"]["present"] is True
    assert manifest["pdfs"]["count"] == 1
    assert manifest["database"]["sha256"]
```

- [ ] **Step 2: Run test to verify RED**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_create_backup_writes_manifest_sqlite_key_and_pdfs -q`

Expected: FAIL because `create_backup` is not implemented.

- [ ] **Step 3: Implement backup creation**

Implementation requirements:

- create `<data_dir>/backups`
- snapshot live SQLite using `sqlite3.Connection.backup()` into a temp file
- hash database snapshot, master key, and PDFs with SHA-256
- write `manifest.json`, `papermind.sqlite`, optional `master.key`, and PDFs into a temporary zip
- replace the temporary zip with final `papermind-backup-YYYYMMDD-HHMMSS.zip`
- remove temp files in `finally`
- return `{"filename", "path", "size_bytes", "modified_at", "manifest"}`

- [ ] **Step 4: Run test to verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_create_backup_writes_manifest_sqlite_key_and_pdfs -q`

Expected: PASS.

---

## Task 3: Backup Listing and Safe Resolution

**Files:**
- Modify: `backend/app/archive/service.py`
- Test: `backend/tests/test_archive.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_list_backups_includes_malformed_zip_without_crashing(env):
    from sqlmodel import Session

    from app.archive.service import create_backup, list_backups
    from app.db.engine import get_engine

    with Session(get_engine()) as session:
        create_backup(session)

    bad = env / "data" / "backups" / "bad.zip"
    bad.write_text("not a zip", encoding="utf-8")

    rows = list_backups()

    assert len(rows) == 2
    assert any(row["filename"] == "bad.zip" and row["error"] for row in rows)


def test_resolve_backup_rejects_path_traversal(env):
    import pytest

    from app.archive.service import resolve_backup

    backup_dir = env / "data" / "backups"
    backup_dir.mkdir(parents=True)
    (backup_dir / "ok.zip").write_bytes(b"zip")

    assert resolve_backup("ok.zip") == backup_dir / "ok.zip"
    with pytest.raises(FileNotFoundError):
        resolve_backup("../master.key")
    with pytest.raises(FileNotFoundError):
        resolve_backup("missing.zip")
```

- [ ] **Step 2: Run tests to verify RED**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_list_backups_includes_malformed_zip_without_crashing tests/test_archive.py::test_resolve_backup_rejects_path_traversal -q`

Expected: FAIL because listing/resolution functions are missing.

- [ ] **Step 3: Implement list and safe resolution**

Implementation requirements:

- list only `*.zip` directly under `<data_dir>/backups`
- sort newest first by modified time
- attempt to read `manifest.json`; for malformed zip, set `error`
- `resolve_backup(filename)` must require `Path(filename).name == filename`
- resolve path and require its parent equals backup dir
- raise `FileNotFoundError` for missing or unsafe filenames

- [ ] **Step 4: Run tests to verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_list_backups_includes_malformed_zip_without_crashing tests/test_archive.py::test_resolve_backup_rejects_path_traversal -q`

Expected: PASS.

---

## Task 4: JSON and BibTeX Exports

**Files:**
- Create: `backend/app/archive/bibtex.py`
- Modify: `backend/app/archive/service.py`
- Test: `backend/tests/test_archive.py`

- [ ] **Step 1: Write failing export tests**

Add:

```python
def test_export_json_excludes_secrets_and_embedding_blobs(env):
    from sqlmodel import Session

    from app.archive.service import export_json
    from app.db.engine import get_engine
    from app.models import Model, Paper, PaperChunk, Provider, Summary

    with Session(get_engine()) as session:
        provider = Provider(name="sf", type="openai_compat", api_key_encrypted="ciphertext")
        paper = Paper(source="arxiv", title="Vector Paper", authors_json='["Ada Lovelace"]')
        session.add(provider)
        session.add(paper)
        session.commit()
        session.refresh(provider)
        session.refresh(paper)
        session.add(Model(provider_id=provider.id, model_id="BAAI/bge-m3", role_default="embedding"))
        session.add(Summary(paper_id=paper.id, content_json='{"method":"retrieval"}'))
        session.add(PaperChunk(paper_id=paper.id, ordinal=0, text="chunk text", embedding=b"secret-vector", embedding_model="BAAI/bge-m3"))
        session.commit()

        exported = export_json(session)

    assert exported["archive_schema_version"] == 1
    assert exported["papers"][0]["title"] == "Vector Paper"
    assert exported["providers"][0]["name"] == "sf"
    assert "api_key_encrypted" not in exported["providers"][0]
    assert exported["chunks"][0]["text"] == "chunk text"
    assert "embedding" not in exported["chunks"][0]


def test_export_bibtex_formats_doi_arxiv_author_venue_and_abstract(env):
    from sqlmodel import Session

    from app.archive.service import export_bibtex
    from app.db.engine import get_engine
    from app.models import Paper

    with Session(get_engine()) as session:
        session.add(
            Paper(
                source="arxiv",
                title="Attention Is All You Need",
                authors_json='["Ashish Vaswani", "Noam Shazeer"]',
                abstract="Transformer model",
                year=2017,
                venue="NeurIPS",
                doi="10.5555/test",
                arxiv_id="1706.03762",
            )
        )
        session.commit()

        bibtex = export_bibtex(session)

    assert "@article{vaswani2017attention" in bibtex
    assert "title = {Attention Is All You Need}" in bibtex
    assert "author = {Ashish Vaswani and Noam Shazeer}" in bibtex
    assert "year = {2017}" in bibtex
    assert "journal = {NeurIPS}" in bibtex
    assert "doi = {10.5555/test}" in bibtex
    assert "eprint = {1706.03762}" in bibtex
    assert "archivePrefix = {arXiv}" in bibtex
    assert "abstract = {Transformer model}" in bibtex
```

- [ ] **Step 2: Run tests to verify RED**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_export_json_excludes_secrets_and_embedding_blobs tests/test_archive.py::test_export_bibtex_formats_doi_arxiv_author_venue_and_abstract -q`

Expected: FAIL because export functions are missing.

- [ ] **Step 3: Implement JSON export**

Implementation requirements:

- include papers, summaries, concepts, paper-concept links, analysis runs, chunks without embeddings, providers without `api_key_encrypted`, models, suggestions, conversations, messages, usage rows, and skills
- parse JSON string fields into JSON values when valid
- preserve raw strings when malformed JSON appears
- include `exported_at` UTC ISO timestamp and `archive_schema_version = 1`

- [ ] **Step 4: Implement BibTeX formatter**

Implementation requirements:

- use first author surname + year + first title word for stable citekey
- lowercase citekey and strip non-alphanumeric characters
- skip deleted papers
- escape `\`, `{`, and `}`
- include `journal` for venue
- include `eprint` plus `archivePrefix = {arXiv}` for arXiv ids

- [ ] **Step 5: Run tests to verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py::test_export_json_excludes_secrets_and_embedding_blobs tests/test_archive.py::test_export_bibtex_formats_doi_arxiv_author_venue_and_abstract -q`

Expected: PASS.

---

## Task 5: Archive API

**Files:**
- Create: `backend/app/api/archive_api.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_archive_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

- `GET /api/archive/status` returns counts
- `POST /api/archive/backup` creates a zip
- `GET /api/archive/backups` lists it
- `GET /api/archive/backups/{filename}` downloads it
- `GET /api/archive/backups/..%2Fmaster.key` returns 404
- `GET /api/archive/export/json` returns downloadable JSON without encrypted keys
- `GET /api/archive/export/bibtex` returns downloadable BibTeX

- [ ] **Step 2: Run API tests to verify RED**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive_api.py -q`

Expected: FAIL with 404s because router is not registered.

- [ ] **Step 3: Implement archive router**

Routes:

- `GET /archive/status`
- `POST /archive/backup`
- `GET /archive/backups`
- `GET /archive/backups/{filename}`
- `GET /archive/export/json`
- `GET /archive/export/bibtex`

Implementation notes:

- use `FileResponse` for backup downloads
- use `Response` for JSON and BibTeX exports with `Content-Disposition: attachment`
- convert `FileNotFoundError` in backup download to 404
- convert missing database during backup to 409

- [ ] **Step 4: Include router in `create_app()`**

Import `archive_router` in `backend/app/main.py` and call:

```python
app.include_router(archive_router, prefix="/api")
```

- [ ] **Step 5: Run API tests to verify GREEN**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive_api.py -q`

Expected: PASS.

---

## Task 6: Frontend Data Safety Section

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Add frontend API methods**

Add types for `ArchiveStatus` and `BackupInfo`.

Add methods:

- `archiveStatus()`
- `createBackup()`
- `listBackups()`
- `downloadBackupUrl(filename)`
- `exportJsonUrl()`
- `exportBibtexUrl()`

Download/export methods should return URLs because the browser handles file downloads directly.

- [ ] **Step 2: Add Settings state and loader**

Add state:

- `archiveStatus`
- `backups`
- `archiveBusy`
- `archiveMsg`

Load archive status and backup list in the existing `load()` function.

- [ ] **Step 3: Add compact Data Safety section**

Add a `section.card` before Token Usage with:

- database/PDF/paper/chunk/provider status
- backup creation button
- backup list with direct download links
- JSON export link
- BibTeX export link
- warning that backup zips contain `master.key` and must be kept private
- warning that restore is not implemented yet

- [ ] **Step 4: Run frontend build**

Run: `cd frontend && npm.cmd run build`

Expected: PASS.

---

## Task 7: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused backend archive tests**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_archive.py tests/test_archive_api.py -q`

Expected: all archive tests pass.

- [ ] **Step 2: Run full backend suite**

Run: `cd backend && .venv\Scripts\python -m pytest`

Expected: all tests pass.

- [ ] **Step 3: Run frontend production build**

Run: `cd frontend && npm.cmd run build`

Expected: build exits 0.

- [ ] **Step 4: Inspect changed files**

Run: `git diff -- backend/app/archive backend/app/api/archive_api.py backend/app/main.py backend/tests/test_archive.py backend/tests/test_archive_api.py frontend/src/api.ts frontend/src/pages/Settings.tsx docs/superpowers`

Expected: diff matches this plan and does not include unrelated rewrites.

