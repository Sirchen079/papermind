from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class PaperReadingState(SQLModel, table=True):
    __tablename__ = "paperreadingstate"

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True, unique=True)
    status: str = Field(default="unread", index=True)
    priority: str = Field(default="normal", index=True)
    rating: int | None = None
    relevance: int | None = Field(default=None, index=True)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_read_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class PaperNote(SQLModel, table=True):
    __tablename__ = "papernote"

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    kind: str = "note"
    content: str
    tags_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class PaperExcerpt(SQLModel, table=True):
    __tablename__ = "paperexcerpt"

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    quote: str
    page: int | None = None
    section: str | None = None
    locator: str | None = None
    note: str | None = None
    tags_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ReviewMatrixEntry(SQLModel, table=True):
    __tablename__ = "reviewmatrixentry"

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True, unique=True)
    problem: str | None = None
    method: str | None = None
    dataset: str | None = None
    metrics: str | None = None
    results: str | None = None
    limitations: str | None = None
    novelty: str | None = None
    relation_to_thesis: str | None = None
    future_work: str | None = None
    notes: str | None = None
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
