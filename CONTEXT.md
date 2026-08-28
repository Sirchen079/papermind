# PaperMind Context

## Core Terms

- Paper: one imported or ingested literature record.
- Reading Workspace: the per-paper working area for status, notes, excerpts, and review-matrix fields.
- Project: a named research track. It can mean a long-term research direction or a more specific subtopic.
- Research Direction: the top-level project that represents the user's overall master's thesis line.
- Subtopic: a child project nested under a broader project.
- Chapter: a thesis-outline node inside a project. Chapters can nest into sections and subsections.
- PaperLink: a user-authored association between a paper and either a project or a chapter.
- Thesis Workspace: the view that helps organize projects, chapters, and their linked papers.

## Canonical Relationships

- A project may have child projects.
- A chapter belongs to one project and may have child chapters.
- A paper may link to multiple projects and multiple chapters through separate PaperLink records.
- One PaperLink record targets exactly one thing: either a project or a chapter.
- Reading Workspace is per paper and is separate from thesis organization.
