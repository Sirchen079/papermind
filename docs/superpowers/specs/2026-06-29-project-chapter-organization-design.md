# PaperMind Project and Chapter Organization Design

- Date: 2026-06-29
- Status: Draft for user review
- Scope: Phase 3 of turning PaperMind into a three-year master's research literature system

## 1. Purpose

PaperMind now has papers, summaries, concepts, reading states, notes, excerpts, literature-review matrices, backups, and exports. That is enough to manage reading. It is not yet enough to manage a full master's thesis lifecycle.

A master's student does not only read papers. They work inside a research direction, split that direction into concrete projects or subtopics, organize a thesis outline, attach papers to multiple argumentative roles, and reuse the same paper in background, method, comparison, and evidence sections. This phase adds a Project/Chapter model so the library can be organized around the student's research program, not just around papers.

## 2. Non-Goals

This phase does not implement citation-key editing, BibTeX round-trip editing, or Zotero sync.

This phase does not implement advisor meeting notes, milestone tracking, or claim/evidence provenance yet. Those are natural follow-ons once project and chapter structure exists.

This phase does not replace the reading workspace. Projects and chapters should sit on top of it.

## 3. Domain Model

### 3.1 Project

A Project is any named research track the student wants to manage explicitly. It can represent a broad long-term direction or a more specific subtopic.

Fields:

- `id`
- `parent_project_id`: nullable, allows a project tree
- `kind`: `direction`, `topic`, `experiment`, `writing`, `other`
- `name`
- `description`: nullable markdown/text
- `status`: `active`, `paused`, `done`, `archived`
- `sort_order`
- `created_at`
- `updated_at`

Behavior:

- Projects can nest.
- A root project can represent the overall master's thesis line.
- Child projects can represent subtopics, experiments, or temporary working tracks.
- Soft deletion should be avoided for project hierarchy in this phase; archival status is enough for now.

### 3.2 Chapter

A Chapter is part of a writing outline or thesis structure.

Fields:

- `id`
- `project_id`
- `parent_chapter_id`: nullable, supports chapter sections and subsections
- `title`
- `outline`: nullable markdown/text
- `sort_order`
- `status`: `draft`, `in_progress`, `review`, `done`
- `created_at`
- `updated_at`

Behavior:

- Chapters live inside a project.
- Chapters form a tree.
- Root chapters map to thesis chapters like Introduction, Related Work, Method, Experiments, and Conclusion.
- Subchapters can represent sections like 2.1, 2.2, etc.

### 3.3 PaperLink

A PaperLink connects a paper to either a project or a chapter.

Fields:

- `id`
- `paper_id`
- `project_id`: nullable
- `chapter_id`: nullable
- `role`: `background`, `method`, `comparison`, `evidence`, `limitation`, `inspiration`, `related`, `to_read`
- `note`: nullable markdown/text
- `created_at`
- `updated_at`

Behavior:

- One paper can link to multiple projects and chapters.
- One project or chapter can contain many papers.
- A link must point to exactly one target: either a project or a chapter.
- `role` explains why the paper belongs there.

### 3.4 Thesis Workspace

The UI should expose a thesis workspace around the root project.

It should let the user:

- create and rename projects
- nest projects
- create and reorder chapters
- attach and detach papers
- filter papers by project or chapter
- inspect which papers support which chapter

## 4. Current Context

The current app already has:

- a Library page with paper detail modal
- a Reading Workspace inside each paper
- a concept graph for co-occurrence
- settings for providers, models, usage, and data safety
- archive/export support
- navigation that is already dense and utilitarian

This means the new workspace should not introduce a new global app shell. It should live in the Library area, with an optional dedicated Thesis view only if the data model itself demands it.

## 5. Requirements

### 5.1 Project Tree

- The user can create, rename, archive, and reorder projects.
- Projects can be nested.
- A root project can act as the thesis umbrella.
- Archived projects stay visible in history but are visually de-emphasized.

### 5.2 Chapter Tree

- The user can create, rename, reorder, and nest chapters.
- Chapters belong to a project.
- Chapters can be filtered to show only one project tree.

### 5.3 Paper Associations

- A paper can be attached to one or more projects.
- A paper can be attached to one or more chapters.
- Each association can carry a role and a note.
- Association changes must be reversible from the UI.

### 5.4 Filters and Views

- Library should support filtering by project and chapter.
- A thesis workspace view should show the project tree, chapter tree, and linked papers.
- The paper detail modal should show project/chapter links alongside reading workspace data.

### 5.5 Export and Safety

- JSON export should include projects, chapters, and paper links.
- Full backup zip already includes the database, so it will capture these tables automatically.
- BibTeX export remains paper-centric and does not need project/chapter data.

## 6. Architecture

### 6.1 Backend Module

Create a focused backend module for thesis organization:

- `backend/app/thesis/service.py`
- `backend/app/api/thesis_api.py`
- `backend/app/models/thesis.py`

The service should own tree integrity, link validation, and ordering rules. FastAPI routes should stay thin.

### 6.2 Database Models

Add three tables:

- `project`
- `chapter`
- `paperlink`

Suggested indexes:

- `project.parent_project_id`
- `chapter.project_id`
- `chapter.parent_chapter_id`
- `paperlink.paper_id`
- `paperlink.project_id`
- `paperlink.chapter_id`

Suggested constraints:

- `paperlink` must reference exactly one target.
- tree rows must not point to themselves.
- child rows must stay within the same project tree when applicable.

### 6.3 API Design

Minimal route set:

- `GET /api/thesis/projects`
- `POST /api/thesis/projects`
- `PATCH /api/thesis/projects/{project_id}`
- `DELETE /api/thesis/projects/{project_id}` or archive endpoint
- `GET /api/thesis/projects/{project_id}/tree`
- `GET /api/thesis/projects/{project_id}/chapters`
- `POST /api/thesis/projects/{project_id}/chapters`
- `PATCH /api/thesis/chapters/{chapter_id}`
- `DELETE /api/thesis/chapters/{chapter_id}`
- `POST /api/papers/{paper_id}/thesis-links`
- `DELETE /api/papers/{paper_id}/thesis-links/{link_id}`
- `GET /api/thesis/workspace`

### 6.4 Frontend Design

Add a Thesis workspace entry in the Library area first.

The initial layout should be compact and practical:

- left: project tree
- middle: chapter tree for selected project
- right: linked papers and attachment controls

The paper detail modal should show current project/chapter links and allow attaching the paper to additional targets.

## 7. Data Flow

Opening Thesis workspace:

1. Frontend loads the project tree and the current thesis root.
2. Frontend loads chapters for the selected project.
3. Frontend loads papers linked to the current selection.

Attaching a paper:

1. User selects a project or chapter target.
2. Frontend sends a paper-link create request.
3. Backend validates the target and creates the association.
4. Frontend refreshes the local tree/paper list.

Reordering a tree:

1. User drags a node or uses up/down controls.
2. Frontend sends order updates.
3. Backend persists sort order and returns the updated tree.

## 8. Testing Strategy

Backend tests must cover:

- project creation and nesting
- chapter creation and nesting
- paper-link creation and deletion
- role validation
- cross-project safety rules
- JSON export includes thesis tables
- soft-deleted papers do not appear in thesis views

Frontend verification must cover:

- thesis workspace loads
- project/chapter tree renders
- paper attachment UI works
- paper detail modal shows thesis associations

Full verification:

- backend pytest
- frontend build
- HTTP smoke test that creates a project, chapter, and paper link in a fresh temp database

## 9. Acceptance Criteria

This phase is complete when:

- the system can represent both long-term research directions and specific subtopics as projects
- projects can nest
- chapters can nest under projects
- papers can be linked to multiple projects or chapters
- the Library can filter and inspect those links
- JSON export includes the thesis organization data
- the rest of the app still passes tests and builds

## 10. Next Phase

After this phase, the best next step is citation workflow: citekeys, BibTeX round-tripping, and Zotero-compatible export, because project/chapter links then have a place to point to in actual thesis writing.
