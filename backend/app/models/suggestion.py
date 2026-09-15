from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Suggestion(SQLModel, table=True):
    """A proactive, AI/agent-generated insight surfaced to the user.

    Kinds:
      - concept_link: two library papers share concept(s) — "these are related".
      - concept_hub:  a concept spans N papers — "this is a central theme".

    Suggestions are generated deterministically from the knowledge graph after
    ingest (see app.knowledge.suggest), so they're reproducible and cheap. The
    ``dedup_key`` makes generation idempotent: re-scanning never creates dupes.
    """

    __tablename__ = "suggestion"
    id: int | None = Field(default=None, primary_key=True)
    kind: str  # concept_link | concept_hub
    title: str
    detail_json: str = Field(default="{}")  # structured payload for the UI
    paper_id: int | None = Field(default=None, foreign_key="paper.id")  # subject paper
    related_paper_id: int | None = Field(default=None, foreign_key="paper.id")
    status: str = Field(default="new", index=True)  # new | seen | dismissed | accepted
    weight: float = 0.0  # strength / shared-concept count
    dedup_key: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
