from datetime import datetime
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel
from app.models.base import utcnow


class WikiPage(SQLModel, table=True):
    __tablename__ = 'wikipage'
    id: str = Field(primary_key=True)
    title: str
    version: int = 0  # Optimistic lock includes adoption, review and archive changes.
    adopted_revision: int | None = None
    archived: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WikiRevision(SQLModel, table=True):
    __tablename__ = 'wikirevision'
    __table_args__ = (UniqueConstraint('page_id', 'number'), UniqueConstraint('page_id', 'request_id'))
    id: int | None = Field(default=None, primary_key=True)
    page_id: str = Field(foreign_key='wikipage.id', index=True)
    number: int
    request_id: str
    input_hash: str
    content: str
    evidence_json: str = '[]'
    references_json: str = '[]'
    support_status: str = 'pending'
    review_note: str = ''
    origin: str = 'researcher'  # researcher | model | research_import | copied
    change_note: str = ''
    created_at: datetime = Field(default_factory=utcnow)


class WikiUpdate(SQLModel, table=True):
    __tablename__ = 'wikiupdate'
    id: str = Field(primary_key=True)
    page_id: str = Field(foreign_key='wikipage.id', index=True)
    base_version: int
    request_hash: str
    inputs_json: str
    status: str = 'queued'
    result_json: str | None = None
    revision_number: int | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WikiCopy(SQLModel, table=True):
    __tablename__ = 'wikicopy'
    request_id: str = Field(primary_key=True)
    source_workspace: str
    source_name: str
    source_page_id: str
    source_revision: int
    source_title: str
    page_id: str = Field(foreign_key='wikipage.id', index=True)
    created_at: datetime = Field(default_factory=utcnow)
