from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.base import utcnow


class PaperCitation(SQLModel, table=True):
    """One reference entry from a paper's bibliography.

    Extracted from the ingested full text (rule-based first, LLM fallback),
    then matched against library papers by doi → arxiv_id → title_norm. Rows
    are the citation graph's source of truth; PaperLink stays reserved for
    user-authored paper↔project/chapter associations.

    The unique (source_paper_id, ref_title_norm) key makes re-extraction
    idempotent. SQLite treats NULL as distinct in unique indexes, so refs
    without a parseable title are kept without dedup.
    """

    __tablename__ = "papercitation"
    __table_args__ = (
        UniqueConstraint("source_paper_id", "ref_title_norm", name="uq_papercitation_source_titlenorm"),
    )

    id: int | None = Field(default=None, primary_key=True)
    source_paper_id: int = Field(foreign_key="paper.id", index=True)
    target_paper_id: int | None = Field(default=None, foreign_key="paper.id", index=True)
    raw_ref: str
    ref_title: str | None = None
    ref_title_norm: str | None = Field(default=None, index=True)
    ref_doi: str | None = Field(default=None, index=True)
    ref_arxiv_id: str | None = Field(default=None, index=True)
    ref_year: int | None = None
    ref_authors_json: str = Field(default="[]")  # JSON-encoded list[str]
    match_status: str = Field(default="unmatched")  # unmatched | matched
    match_confidence: float | None = None  # 0–1, by match strategy
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
