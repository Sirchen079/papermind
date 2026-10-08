"""Literature survey board: AI-assisted discovery with human selection."""
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class LiteratureSurvey(SQLModel, table=True):
    __tablename__ = "literaturesurvey"

    id: int | None = Field(default=None, primary_key=True)
    query: str
    years: int = 2  # look-back window in years
    max_results: int = 20
    status: str = "queued"  # queued|running|ready|error|interrupted
    error: str = ""
    expansion_used: str = "[]"  # JSON list of executed search phrases
    screened: bool = False  # whether LLM screening ran
    import_status: str = "idle"  # idle|running|done
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    finished_at: datetime | None = None


class LiteratureCandidate(SQLModel, table=True):
    __tablename__ = "literaturecandidate"

    id: int | None = Field(default=None, primary_key=True)
    survey_id: int = Field(foreign_key="literaturesurvey.id", index=True)
    openalex_id: str = ""
    doi: str = ""
    arxiv_id: str = ""
    title: str
    year: int | None = None
    venue: str = ""
    authors_json: str = "[]"
    cited_by_count: int = 0
    oa_pdf_url: str = ""
    abstract: str = ""
    relevance: str = ""  # short LLM screening note
    keep: bool | None = None  # LLM suggestion; the human decision is the import
    status: str = "candidate"  # candidate|queued_import|imported|imported_no_pdf|duplicate|failed
    paper_id: int | None = None
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)
