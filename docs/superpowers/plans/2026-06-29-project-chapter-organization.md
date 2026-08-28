# Project and Chapter Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thesis organization layer so projects, chapters, and paper links can represent both long-term research directions and specific subtopics, with the UI able to inspect and attach papers to that structure.

**Architecture:** Add a focused thesis module with three tables: project, chapter, and paperlink. Keep tree integrity and link validation in `app.thesis.service`, expose thin FastAPI routes in `app.api.thesis_api`, and surface the new data in Library plus JSON export. Follow the existing pattern used by reading/archive: service owns business rules, API maps errors, tests prove behavior.

**Tech Stack:** FastAPI, SQLModel, Alembic, React, TypeScript, Vite, pytest.

---

### Task 1: Lock the domain model into code

**Files:**
- Create: `backend/app/models/thesis.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/migrations/versions/<new_revision>_thesis_organization.py`
- Test: `backend/tests/test_thesis_models.py`

- [ ] **Step 1: Write the failing test**

```python
from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Paper, Project, Chapter, PaperLink


def test_thesis_models_roundtrip(tmp_path):
    eng = make_engine(tmp_path / "thesis.sqlite")
    SQLModel.metadata.create_all(eng)

    with Session(eng) as session:
        paper = Paper(source="manual", title="Thesis Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)

        root = Project(name="Master Thesis", kind="direction")
        session.add(root)
        session.commit()
        session.refresh(root)

        child = Project(name="Subtopic", kind="topic", parent_project_id=root.id)
        session.add(child)
        session.commit()
        session.refresh(child)

        chapter = Chapter(project_id=root.id, title="Related Work")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        session.add(PaperLink(paper_id=paper.id, project_id=child.id, role="background"))
        session.add(PaperLink(paper_id=paper.id, chapter_id=chapter.id, role="evidence"))
        session.commit()

        projects = session.exec(select(Project)).all()
        chapters = session.exec(select(Chapter)).all()
        links = session.exec(select(PaperLink)).all()

    assert len(projects) == 2
    assert len(chapters) == 1
    assert len(links) == 2
    assert links[0].role in {"background", "evidence"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_thesis_models.py -v`
Expected: FAIL because `Project`, `Chapter`, and `PaperLink` do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Project(SQLModel, table=True):
    __tablename__ = "project"
    id: int | None = Field(default=None, primary_key=True)
    parent_project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    kind: str = "topic"
    name: str
    description: str | None = None
    status: str = "active"
    sort_order: int = 0
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class Chapter(SQLModel, table=True):
    __tablename__ = "chapter"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    parent_chapter_id: int | None = Field(default=None, foreign_key="chapter.id", index=True)
    title: str
    outline: str | None = None
    sort_order: int = 0
    status: str = "draft"
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class PaperLink(SQLModel, table=True):
    __tablename__ = "paperlink"
    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    chapter_id: int | None = Field(default=None, foreign_key="chapter.id", index=True)
    role: str = "related"
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_thesis_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/thesis.py backend/app/models/__init__.py backend/migrations/versions/<new_revision>_thesis_organization.py backend/tests/test_thesis_models.py
git commit -m "feat: add thesis organization models"
```

### Task 2: Add thesis service rules

**Files:**
- Create: `backend/app/thesis/__init__.py`
- Create: `backend/app/thesis/service.py`
- Test: `backend/tests/test_thesis_service.py`

- [ ] **Step 1: Write the failing test**

```python
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper
from app.thesis.service import create_project, create_chapter, link_paper, get_thesis_workspace


def test_thesis_service_writes_tree_and_links(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Tree Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)

        root = create_project(session, {"name": "Master Thesis", "kind": "direction"})
        child = create_project(session, {"name": "Topic A", "kind": "topic", "parent_project_id": root["id"]})
        chapter = create_chapter(session, root["id"], {"title": "Related Work"})
        link = link_paper(session, paper.id, {"project_id": child["id"], "role": "background"})
        workspace = get_thesis_workspace(session)

    assert root["name"] == "Master Thesis"
    assert child["parent_project_id"] == root["id"]
    assert chapter["project_id"] == root["id"]
    assert link["role"] == "background"
    assert workspace["projects"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_thesis_service.py -v`
Expected: FAIL because `app.thesis.service` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
# implement project/chapter/link CRUD + tree validation + workspace assembly
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_thesis_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/thesis backend/tests/test_thesis_service.py
git commit -m "feat: add thesis service rules"
```

### Task 3: Add thesis API routes

**Files:**
- Create: `backend/app/api/thesis_api.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_thesis_api.py`

- [ ] **Step 1: Write the failing test**

```python
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper


def test_thesis_api_workspace_and_links(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="API Thesis Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        pid = paper.id

    assert client.get("/api/thesis/workspace").status_code == 200
    assert client.post("/api/thesis/projects", json={"name": "Thesis", "kind": "direction"}).status_code == 201
    assert client.post(f"/api/papers/{pid}/thesis-links", json={"project_id": 1, "role": "related"}).status_code in {200, 201}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_thesis_api.py -v`
Expected: FAIL with 404/route missing.

- [ ] **Step 3: Write the minimal implementation**

```python
# thin routes for project/chapter/tree/link/workspace
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_thesis_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/thesis_api.py backend/app/main.py backend/tests/test_thesis_api.py
git commit -m "feat: add thesis api"
```

### Task 4: Include thesis data in exports

**Files:**
- Modify: `backend/app/archive/service.py`
- Test: `backend/tests/test_archive.py`

- [ ] **Step 1: Write the failing test**

```python
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper
from app.archive.service import export_json
from app.thesis.service import create_project


def test_export_json_includes_thesis_tables(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Export Thesis Paper")
        session.add(paper)
        session.commit()
        create_project(session, {"name": "Thesis", "kind": "direction"})
        exported = export_json(session)

    assert exported["projects"]
    assert exported["chapters"] == []
    assert exported["paper_links"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_archive.py -v`
Expected: FAIL because thesis tables are not exported yet.

- [ ] **Step 3: Write the minimal implementation**

```python
# add projects, chapters, paper_links to export_json()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_archive.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/archive/service.py backend/tests/test_archive.py
git commit -m "feat: export thesis organization data"
```

### Task 5: Surface thesis data in the Library UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/Library.tsx`
- Test: `frontend` build

- [ ] **Step 1: Write the failing test or use build as the gate**

```typescript
// Add API types and a Thesis workspace panel wired into Library.
```

- [ ] **Step 2: Run the build to verify the UI is currently missing the new data**

Run: `npm.cmd run build`
Expected: PASS before changes; after wiring the new UI, still PASS.

- [ ] **Step 3: Write the minimal implementation**

```typescript
// add thesis API methods + project/chapter tree panel + link controls
```

- [ ] **Step 4: Run the build again**

Run: `npm.cmd run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/pages/Library.tsx
git commit -m "feat: add thesis workspace ui"
```

### Task 6: Verify the end-to-end flow

**Files:**
- No new files; verification only

- [ ] **Step 1: Run backend tests**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

Run: `npm.cmd run build`
Expected: build succeeds.

- [ ] **Step 3: Run a fresh HTTP smoke test**

```python
# seed a paper, create project, create chapter, attach link, fetch workspace, export JSON
```

Expected: 200/201 responses and thesis data present in the workspace/export.

- [ ] **Step 4: Report results**

Summarize what was added and any remaining gaps.
```
