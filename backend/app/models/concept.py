from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Concept(SQLModel, table=True):
    __tablename__ = "concept"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    normalized_key: str = Field(index=True, unique=True)  # G1: dedup/merge key
    type: str | None = None  # method | dataset | problem | domain
    description: str | None = None
    parent_concept_id: int | None = Field(default=None, foreign_key="concept.id")
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class PaperConcept(SQLModel, table=True):
    __tablename__ = "paperconcept"
    paper_id: int = Field(foreign_key="paper.id", primary_key=True)
    concept_id: int = Field(foreign_key="concept.id", primary_key=True)
    weight: float = 1.0
    evidence: str | None = None
    run_id: int | None = Field(default=None, foreign_key="analysisrun.id")
