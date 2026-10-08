from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class PaperCard(SQLModel, table=True):
    """One paper-level reading card; rebuilt only when inputs or prompt change."""

    __tablename__ = "papercard"
    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", unique=True, index=True)
    fingerprint: str = Field(index=True)  # digest of inputs + prompt version + model
    status: str = "done"  # done | fallback | metadata_only
    card_json: str = "{}"
    model: str | None = None
    warning: str = ""
    version: int = 0  # bumped when the researcher edits the card
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
