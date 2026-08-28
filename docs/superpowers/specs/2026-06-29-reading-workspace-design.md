# PaperMind Reading Workspace Design

- Date: 2026-06-29
- Status: Draft for user review
- Scope: Phase 2 of turning PaperMind into a three-year master's research literature system

## 1. Purpose

PaperMind can already ingest papers, summarize them with an LLM, extract concepts, build graph/RAG context, chat over the library, suggest related work, and protect data through backup/export. The next maturity step is to turn stored papers into durable research work.

A master's student does not only collect papers. They repeatedly decide what to read, record why a paper matters, capture evidence, compare methods, prepare group-meeting notes, write a literature review, and later reuse those notes in thesis chapters. This phase adds a Reading Workspace so every paper can accumulate structured human research judgment, not just AI-generated summaries.

## 2. Non-Goals

This phase does not implement a full PDF annotation engine. It may store page numbers and quoted text, but it will not render PDF pages with geometric highlight coordinates.

This phase does not implement Zotero sync, citation key editing, project/chapter planning, advisor meeting notes, or multi-user collaboration. Those depend on the reading assets added here and should be built later.

This phase does not ask the LLM to automatically fill every matrix field. AI-assisted extraction can be added later. The first version must make the user's own reading notes reliable and easy to edit.

## 3. Current Context

The current app has these relevant surfaces:

- `Library`: paper list, ingest controls, detail modal, AI summary, concepts, full-text-related actions, and related-paper discovery.
- `Chat`: RAG over paper chunks and summaries.
- `Graph`: paper/concept graph.
- `Settings`: providers, usage, RAG reindexing, and Data Safety.

The current paper detail modal shows metadata, abstract, concepts, parse-confidence warnings, AI summary, analysis retry, and related-paper discovery. It does not store user reading progress, user notes, reusable quotations, or literature-review comparison fields.

The Reading Workspace should start inside the Library paper detail modal rather than adding a new primary navigation item. The user is already looking at a paper when they need to record reading work. A global matrix view can be added as a compact Library subview in the same phase.

## 4. Product Requirements

### 4.1 Reading State

Every paper can have one reading state row.

Fields:

- `status`: `unread`, `queued`, `reading`, `read`, `skipped`
- `priority`: `low`, `normal`, `high`
- `rating`: integer 1-5, nullable
- `relevance`: integer 1-5, nullable
- `started_at`: nullable timestamp
- `finished_at`: nullable timestamp
- `last_read_at`: nullable timestamp
- `updated_at`: timestamp

Behavior:

- New papers default to no explicit reading row. The API presents that as `status = unread`, `priority = normal`.
- Setting status to `reading` fills `started_at` if it is empty and updates `last_read_at`.
- Setting status to `read` fills `finished_at` if it is empty and updates `last_read_at`.
- Rating and relevance are independent: rating is paper quality; relevance is usefulness to the student's own thesis.

### 4.2 User Notes

Every paper can have multiple notes.

Fields:

- `id`
- `paper_id`
- `kind`: `note`, `question`, `idea`, `critique`, `todo`
- `content`: Markdown text
- `tags_json`: JSON list of strings
- `created_at`
- `updated_at`

Behavior:

- Notes are sorted newest first in the paper detail modal.
- Empty note content is rejected.
- Notes belong to a paper and disappear from normal UI when the paper is soft-deleted.
- Notes are preserved in backups and JSON export.

### 4.3 Excerpts

Every paper can have multiple reusable excerpts.

Fields:

- `id`
- `paper_id`
- `quote`: copied original text
- `page`: nullable integer
- `section`: nullable string, such as Introduction, Method, Experiments
- `locator`: nullable string for loose location text, such as paragraph heading or PDF search text
- `note`: nullable Markdown explanation
- `tags_json`: JSON list of strings
- `created_at`
- `updated_at`

Behavior:

- Empty quote text is rejected.
- Page numbers must be positive when provided.
- Excerpts are not geometric highlights. They are stable text evidence that can be reused in writing.
- Excerpts are sorted by page when page exists, then newest first.

### 4.4 Literature Review Matrix

Every paper can have one literature review matrix row.

Fields:

- `problem`: what problem the paper addresses
- `method`: core method or system design
- `dataset`: datasets, benchmarks, or study material
- `metrics`: evaluation metrics
- `results`: main empirical findings
- `limitations`: weaknesses or threats
- `novelty`: what is actually new
- `relation_to_thesis`: how it relates to the student's own direction
- `future_work`: follow-up ideas or how to extend it
- `notes`: extra structured remarks
- `updated_at`

Behavior:

- The matrix is editable in the paper detail modal.
- Empty fields are allowed; the row can be saved incrementally.
- A global matrix view lists one row per non-deleted paper with title, year, status, relevance, and the matrix fields.
- The global matrix can be filtered by reading status and searched by title, author, concept, or matrix text.

### 4.5 Library List Integration

The Library list should expose reading state without becoming crowded.

Each paper row/card should show:

- reading status chip
- high priority indicator, when priority is high
- relevance score, when set

The Library filters should include:

- reading status
- high priority only
- minimum relevance

### 4.6 Paper Detail Integration

The existing paper detail modal gains a Reading Workspace area with compact tabs or sections:

- Overview: status, priority, rating, relevance, started/finished timestamps
- Matrix: literature review fields
- Notes: create/edit/delete notes
- Excerpts: create/edit/delete excerpts

The UI should be dense, utilitarian, and optimized for repeated use. It should not use a marketing layout or a separate hero-like page.

### 4.7 Archive and Export Integration

Full backup zip automatically includes reading data because it includes the SQLite snapshot.

JSON export must include:

- reading states
- notes
- excerpts
- matrix rows

BibTeX export does not include reading data.

## 5. Architecture

### 5.1 Backend Module

Create a focused backend module:

- `backend/app/reading/service.py`
- `backend/app/api/reading_api.py`
- `backend/app/models/reading.py`

Service interface:

- `get_reading_workspace(session, paper_id) -> dict`
- `patch_reading_state(session, paper_id, payload) -> dict`
- `upsert_review_matrix(session, paper_id, payload) -> dict`
- `create_note(session, paper_id, payload) -> dict`
- `patch_note(session, paper_id, note_id, payload) -> dict`
- `delete_note(session, paper_id, note_id) -> None`
- `create_excerpt(session, paper_id, payload) -> dict`
- `patch_excerpt(session, paper_id, excerpt_id, payload) -> dict`
- `delete_excerpt(session, paper_id, excerpt_id) -> None`
- `list_review_matrix(session, filters) -> list[dict]`

FastAPI route functions should stay thin and delegate validation/business rules to the service layer or Pydantic input models.

### 5.2 Database Models

Add four tables:

- `paperreadingstate`
- `papernote`
- `paperexcerpt`
- `reviewmatrixentry`

Foreign keys point to `paper.id`. The app already uses soft deletion for papers, so these rows are not deleted when a paper is soft-deleted. Normal UI and list APIs filter out deleted papers.

Indexes:

- `paperreadingstate.paper_id` unique
- `papernote.paper_id`
- `paperexcerpt.paper_id`
- `reviewmatrixentry.paper_id` unique
- `paperreadingstate.status`
- `paperreadingstate.priority`
- `paperreadingstate.relevance`

### 5.3 API Design

Routes:

- `GET /api/papers/{paper_id}/reading`
- `PATCH /api/papers/{paper_id}/reading/state`
- `PUT /api/papers/{paper_id}/reading/matrix`
- `POST /api/papers/{paper_id}/reading/notes`
- `PATCH /api/papers/{paper_id}/reading/notes/{note_id}`
- `DELETE /api/papers/{paper_id}/reading/notes/{note_id}`
- `POST /api/papers/{paper_id}/reading/excerpts`
- `PATCH /api/papers/{paper_id}/reading/excerpts/{excerpt_id}`
- `DELETE /api/papers/{paper_id}/reading/excerpts/{excerpt_id}`
- `GET /api/reading/matrix`

Error handling:

- Missing or soft-deleted paper returns 404.
- Note/excerpt id that does not belong to the paper returns 404.
- Invalid status, priority, kind, rating, relevance, or page returns 422.
- Empty note content or empty quote returns 422.

### 5.4 Frontend API

Add types and methods to `frontend/src/api.ts`:

- `ReadingWorkspace`
- `ReadingState`
- `PaperNote`
- `PaperExcerpt`
- `ReviewMatrixEntry`
- `getReadingWorkspace(paperId)`
- `patchReadingState(paperId, body)`
- `saveReviewMatrix(paperId, body)`
- `createNote(paperId, body)`
- `patchNote(paperId, noteId, body)`
- `deleteNote(paperId, noteId)`
- `createExcerpt(paperId, body)`
- `patchExcerpt(paperId, excerptId, body)`
- `deleteExcerpt(paperId, excerptId)`
- `reviewMatrix(params)`

### 5.5 Frontend UI

Modify `frontend/src/pages/Library.tsx` first, without splitting the page into new components unless the file becomes too hard to work with.

If the modal grows too large during implementation, extract focused components:

- `frontend/src/components/ReadingWorkspace.tsx`
- `frontend/src/components/ReviewMatrixPanel.tsx`
- `frontend/src/components/NotesPanel.tsx`
- `frontend/src/components/ExcerptsPanel.tsx`

The initial implementation should prefer extraction if it keeps `Library.tsx` readable.

## 6. Data Flow

Opening a paper detail modal:

1. `api.getPaper(id)` loads paper metadata, AI summary, concepts, analysis status, and full text.
2. `api.getReadingWorkspace(id)` loads reading state, matrix, notes, and excerpts.
3. The detail modal renders the existing AI/retrieval information plus the Reading Workspace.

Saving reading state:

1. User changes status, priority, rating, or relevance.
2. Frontend sends a PATCH request.
3. Backend validates values, upserts the row, applies timestamp rules, and returns the updated state.
4. Frontend updates the modal and refreshes the paper list chips.

Saving notes/excerpts:

1. User creates or edits content.
2. Backend validates non-empty content and ownership.
3. Frontend updates the local workspace state without reloading the full paper list.

Global matrix:

1. User switches Library into Matrix view or opens a compact Matrix panel.
2. Frontend calls `GET /api/reading/matrix`.
3. Backend joins papers, reading state, and matrix entries for non-deleted papers.

## 7. Testing Strategy

Backend tests must cover:

- migration creates all reading tables and indexes
- default workspace for a paper with no reading rows
- state upsert timestamp rules for `reading` and `read`
- invalid status, priority, rating, relevance, and page validation
- creating, patching, deleting notes
- creating, patching, deleting excerpts
- ownership checks for note/excerpt ids
- matrix upsert and global matrix listing
- soft-deleted papers are hidden from workspace and matrix APIs
- JSON export includes reading states, notes, excerpts, and matrix rows

Frontend verification:

- `npm.cmd run build`
- open Library, select a paper, edit reading state, add note, add excerpt, edit matrix
- confirm status chips appear in the list

Full verification:

- `backend/.venv/Scripts/python -m pytest`
- `frontend/npm.cmd run build`
- real server smoke test with one seeded paper that creates state, note, excerpt, and matrix via HTTP

## 8. Later Phases

After this phase, the next mature research workflow phases are:

1. Citation workflow: citekey editing, BibTeX import/export refinement, and Zotero-compatible exports.
2. Project and thesis organization: collections, chapters, advisor meeting notes, evidence links.
3. AI-assisted matrix fill: propose matrix fields from summary/full text, but require user confirmation.
4. PDF page rendering and geometric highlights.
5. Safe restore: inspect backup, create pre-restore backup, typed confirmation, replace data directory safely.

## 9. Acceptance Criteria

This phase is complete when:

- each paper can store and show reading status, priority, rating, and relevance
- each paper can store, edit, and delete notes
- each paper can store, edit, and delete excerpts with optional page/section/locator
- each paper can store and edit a literature review matrix row
- Library list shows reading state chips and supports reading filters
- global matrix view lists non-deleted papers with matrix fields
- JSON export includes reading workspace data and still excludes secrets
- all backend tests pass
- frontend build passes
- a real HTTP smoke test verifies the reading workspace APIs

