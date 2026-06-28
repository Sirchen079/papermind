from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Paper(SQLModel, table=True):
    __tablename__ = "paper"
    id: int | None = Field(default=None, primary_key=True)
    source: str  # pdf | arxiv | bibtex | manual
    source_ref: str | None = None  # arxiv_id / doi / file path
    title: str | None = None
    authors_json: str = Field(default="[]")  # JSON-encoded list[str]
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = Field(default=None, index=True)
    arxiv_id: str | None = Field(default=None, index=True)
    pdf_path: str | None = None
    full_text: str | None = None
    parse_confidence: float | None = None
    title_norm: str | None = Field(default=None, index=True)
    is_deleted: bool = False
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class AnalysisRun(SQLModel, table=True):
    __tablename__ = "analysisrun"
    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    provider_id: int | None = Field(default=None, foreign_key="provider.id")
    model: str | None = None
    started_at: datetime = Field(default_factory=utcnow, nullable=False)
    finished_at: datetime | None = None
    status: str = "running"  # running | done | failed
    is_current: bool = True


class Summary(SQLModel, table=True):
    __tablename__ = "summary"
    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    run_id: int | None = Field(default=None, foreign_key="analysisrun.id")
    content_json: str | None = None  # structured: {problem, method, ...}
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
