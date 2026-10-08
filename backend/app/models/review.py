"""Resumable library reviews. Paper/section checkpoints stay small at 1000 papers."""
from datetime import datetime
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint
from app.models.base import utcnow


class LibraryReview(SQLModel, table=True):
    __tablename__ = 'libraryreview'
    id: str = Field(primary_key=True)
    question: str
    status: str = 'draft'
    stage: str = '准备材料'
    run_token: str = ''
    error: str = ''
    outline_json: str = '[]'
    content: str = ''
    version: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ReviewPaper(SQLModel, table=True):
    __tablename__ = 'reviewpaper'
    __table_args__ = (UniqueConstraint('review_id', 'paper_id'),)
    id: int | None = Field(default=None, primary_key=True)
    review_id: str = Field(foreign_key='libraryreview.id', index=True)
    paper_id: int  # preserve snapshots after a source is removed
    title: str = ''
    citation_key: str = ''
    fingerprint: str = Field(default='', index=True)
    status: str = 'pending'  # done | fallback | missing | pending
    coverage: str = ''
    analysis: str = ''
    evidence_json: str = '[]'
    warning: str = ''
    reused: bool = False


class ReviewSection(SQLModel, table=True):
    __tablename__ = 'reviewsection'
    __table_args__ = (UniqueConstraint('review_id', 'ordinal'),)
    id: int | None = Field(default=None, primary_key=True)
    review_id: str = Field(foreign_key='libraryreview.id', index=True)
    ordinal: int
    title: str
    fingerprint: str = ''
    content: str = ''
    evidence_json: str = '[]'
    warning: str = ''


class ReviewRevision(SQLModel, table=True):
    __tablename__ = 'reviewrevision'
    id: int | None = Field(default=None, primary_key=True)
    review_id: str = Field(foreign_key='libraryreview.id', index=True)
    version: int
    content: str
    created_at: datetime = Field(default_factory=utcnow)


class ReviewMap(SQLModel, table=True):
    """One literature map per review: themes, assignments, later syntheses."""
    __tablename__ = 'reviewmap'
    id: int | None = Field(default=None, primary_key=True)
    review_id: str = Field(foreign_key='libraryreview.id', unique=True, index=True)
    status: str = 'draft'  # draft | running | ready | paused | failed
    stage: str = '准备材料'
    run_token: str = ''
    error: str = ''
    themes_json: str = '[]'  # [{id, name, definition, include, exclude}]
    themes_fingerprint: str = ''
    assignments_json: str = '{}'  # {paper_id: {themes, reason, fingerprint}}
    syntheses_json: str = '{}'
    overview_json: str = '{}'
    version: int = 0
    updated_at: datetime = Field(default_factory=utcnow)
