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
