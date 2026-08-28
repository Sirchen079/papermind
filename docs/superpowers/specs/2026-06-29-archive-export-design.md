# PaperMind Archive and Export Design

- Date: 2026-06-29
- Status: Draft for user review
- Scope: Phase 1 of turning PaperMind into a three-year research literature system

## 1. Purpose

PaperMind already supports importing papers, AI summaries, concept extraction, graph views, RAG chat, provider settings, skills, suggestions, and usage tracking. The next maturity step is not another AI feature. It is data safety.

A master's student may spend three years building a private literature library. Losing the SQLite database, uploaded PDFs, encrypted API key master key, AI summaries, or vector index would be worse than temporarily losing chat functionality. This phase adds a reliable archive and export layer so the library can be backed up, inspected, moved, and exported before more long-lived research assets are added.

## 2. Non-Goals

This phase does not implement destructive restore into the live library. Restore is intentionally deferred because overwriting the active database is the riskiest operation in the product. This phase may inspect archive validity, but it will not replace the current `backend/data` directory.

This phase does not add PDF annotation, literature review matrices, citation managers, author normalization, or Zotero sync. Those are later maturity phases that should sit on top of a reliable archive/export foundation.

## 3. Current Context

The app stores user data under `backend/data` by default:

- `papermind.sqlite`: SQLite database, including papers, summaries, concepts, chunks, conversations, settings, providers, usage, skills, and suggestions.
- `master.key`: Fernet master key required to decrypt stored provider API keys.
- `pdfs/`: uploaded or fetched PDF files.

The app already has these user-facing areas:

- Library
- Suggestions
- Graph
- Chat
- Skills
- Settings

The archive/export feature should live in Settings as a new "Data Safety" section, rather than as a separate primary navigation item. It is an operational tool, not a daily research workspace.

## 4. Product Requirements

### 4.1 Archive Status

The user can inspect whether the local data store is safe to archive.

Status must report:

- database path and existence
- database size
- data directory path
- master key existence
- PDF directory existence
- PDF count and total bytes
- paper count
- summary count
- concept count
- chunk count
- provider count
- latest backup, if one exists

No API key plaintext is ever returned.

### 4.2 Full Backup Zip

The user can create a complete backup zip.

The zip must contain:

- `manifest.json`
- `papermind.sqlite`
- `master.key`, when present
- every file under `pdfs/`, preserving relative paths

The manifest must contain:

- schema version for the archive format
- created timestamp in UTC ISO format
- app name and archive type
- database file size and sha256
- master key file size and sha256, when present
- PDF file count, total size, and per-file sha256
- paper count
- summary count
- concept count
- chunk count
- provider count

The backup filename format is:

`papermind-backup-YYYYMMDD-HHMMSS.zip`

Backups are stored under:

`<data_dir>/backups/`

### 4.3 Backup Listing and Download

The user can list existing backup zips and download one.

Listing must return:

- filename
- size
- modified timestamp
- manifest summary, when manifest can be read
- an error string when a backup zip is malformed

Download must only allow files inside the configured backup directory. Path traversal such as `../master.key` must be rejected.

### 4.4 JSON Export

The user can export a portable JSON snapshot that does not require the original SQLite schema.

The JSON export must include:

- papers and core metadata
- summaries
- concepts linked to each paper
- analysis status for each paper
- suggestions
- conversations and messages
- usage aggregates or raw usage rows

The JSON export must not include:

- encrypted provider API keys
- master key bytes
- vector embedding blobs

PDF files are not embedded in JSON. Their relative paths are included so the JSON can be paired with a full backup zip.

### 4.5 BibTeX Export

The user can export library metadata as BibTeX for Zotero, Overleaf, and LaTeX workflows.

Each non-deleted paper should produce one entry:

- `@article` by default
- stable citekey derived from first author, year, and title words
- `title`
- `author`
- `year`
- `journal` or `booktitle`, when venue exists
- `doi`, when present
- `eprint` and `archivePrefix = {arXiv}`, when arXiv id exists
- `abstract`, when present

Entries must escape braces and backslashes enough to avoid broken BibTeX syntax.

### 4.6 Frontend

Settings gains a Data Safety section with:

- status summary
- "Create backup" action
- backup list with download buttons
- JSON export button
- BibTeX export button
- clear warning that restore is not implemented yet

The UI should be utilitarian and compact. It should not be a marketing-style page.

## 5. Architecture

### 5.1 Deep Module

Create a backend archive module with a small interface:

- `archive_status() -> ArchiveStatus`
- `create_backup() -> BackupInfo`
- `list_backups() -> list[BackupInfo]`
- `resolve_backup(filename: str) -> Path`
- `export_json() -> dict`
- `export_bibtex() -> str`

This keeps filesystem traversal, SQLite snapshot handling, manifest creation, hashing, and export formatting out of FastAPI route functions.

### 5.2 Backend Files

Expected new files:

- `backend/app/archive/__init__.py`
- `backend/app/archive/service.py`
- `backend/app/archive/bibtex.py`
- `backend/app/api/archive_api.py`
- `backend/tests/test_archive.py`
- `backend/tests/test_archive_api.py`

Expected modified files:

- `backend/app/main.py`
- `frontend/src/api.ts`
- `frontend/src/pages/Settings.tsx`

No database migration is required for the first phase because backups are filesystem artifacts under `data/backups`.

### 5.3 SQLite Backup Method

Use Python's `sqlite3.Connection.backup()` API to copy the live database into a temporary file before zipping. Do not zip the active SQLite file directly, because WAL mode can make a direct file copy inconsistent.

The backup flow:

1. Resolve settings.
2. Create `<data_dir>/backups` if missing.
3. Copy the live SQLite database to a temporary snapshot using SQLite backup API.
4. Hash the snapshot.
5. Hash `master.key`, if present.
6. Hash PDFs.
7. Build `manifest.json`.
8. Write a zip atomically via a temporary zip path.
9. Rename the temporary zip to the final filename.

If any step fails, no partial final backup zip should remain.

## 6. API Design

### GET `/api/archive/status`

Returns archive readiness and counts.

### POST `/api/archive/backup`

Creates a backup zip and returns its metadata.

### GET `/api/archive/backups`

Lists backup zips.

### GET `/api/archive/backups/{filename}`

Downloads a backup zip. Rejects any filename that is not a direct child file of the backup directory.

### GET `/api/archive/export/json`

Returns a JSON export as a downloadable file.

### GET `/api/archive/export/bibtex`

Returns a BibTeX export as a downloadable file.

## 7. Error Handling

- Missing database: status reports `database_exists = false`; backup returns 409 with a clear message.
- Missing master key: backup can still run, but manifest records `master_key_present = false`; status warns that encrypted provider keys cannot be restored without it.
- Missing PDF directory: backup can still run with `pdf_count = 0`.
- Malformed backup zip in listing: include it with an error field instead of failing the whole list.
- Path traversal in download: return 404.
- Export with empty library: return a valid empty export, not an error.

## 8. Security

Backups include `master.key`, because a full restore without it cannot decrypt provider API keys. The UI must warn users that backup zips contain secrets and should be stored privately.

JSON and BibTeX exports are shareable research metadata exports and must not include secrets.

Download endpoints must not accept arbitrary paths. Only filenames inside `<data_dir>/backups` are allowed.

## 9. Testing Strategy

Backend tests must cover:

- status works with an initialized test database
- backup zip contains manifest, SQLite snapshot, master key, and PDFs
- manifest hashes match zip contents
- backup listing returns valid metadata
- malformed zip listing does not crash the endpoint
- backup download rejects path traversal
- JSON export excludes encrypted provider keys and vector blobs
- BibTeX export contains valid entries for DOI, arXiv id, authors, venue, and abstract

Frontend verification:

- `npm.cmd run build`
- manual or HTTP smoke test that Settings can load the archive status endpoint

Full project verification:

- `backend/.venv/Scripts/python -m pytest`
- `frontend/npm.cmd run build`
- real server smoke test for archive status and creating a backup in a temporary data directory

## 10. Later Phases

After this phase, mature research workflow work should proceed in this order:

1. PDF reading states, notes, highlights, and excerpt capture.
2. Literature review matrix: problem, method, dataset, metric, result, limitation, relation to thesis.
3. Citation workflow: citekey editing, BibTeX import/export refinement, Zotero-compatible exports.
4. Safe restore: inspect backup, create pre-restore backup, require typed confirmation, stop app writes, replace data directory, restart.
5. Project and thesis organization: collections, chapters, advisor meeting notes, evidence links.

## 11. Acceptance Criteria

This phase is complete when:

- the Data Safety section appears in Settings
- status reports real local data health
- creating a backup produces a zip with a verified manifest
- the backup can be downloaded
- JSON export downloads without secrets
- BibTeX export downloads and contains all non-deleted papers
- all backend tests pass
- frontend build passes
- a real server smoke test creates a backup in an isolated temp data directory

