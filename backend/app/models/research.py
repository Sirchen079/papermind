"""Persistent research work; projects are optional and evidence stays versioned."""
from datetime import datetime
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel
from app.models.base import utcnow


class ResearchTask(SQLModel, table=True):
    __tablename__ = 'researchtask'
    id: str = Field(primary_key=True)
    question: str
    project_id: int | None = Field(default=None, foreign_key='project.id')
    depth: str = 'evidence'
    paper_ids_json: str
    materials_json: str = '[]'
    steps_json: str = '{}'
    status: str = 'draft'
    stop_reason: str | None = None
    run_token: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ResearchArtifact(SQLModel, table=True):
    __tablename__ = 'researchartifact'
    __table_args__ = (UniqueConstraint('task_id', 'version'),)
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key='researchtask.id', index=True)
    version: int
    content: str
    evidence_refs_json: str = '[]'
    evidence_snapshot_json: str = '[]'
    claim_kind: str = 'researcher_judgment'
    support_status: str = 'pending'
    review_note: str = ''
    adopted: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class ResearchReuse(SQLModel, table=True):
    __tablename__ = 'researchreuse'
    __table_args__ = (UniqueConstraint('task_id', 'kind'),)
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key='researchtask.id', index=True)
    artifact_id: int = Field(foreign_key='researchartifact.id')
    kind: str  # meeting | plan
    content: str
    created_at: datetime = Field(default_factory=utcnow)
