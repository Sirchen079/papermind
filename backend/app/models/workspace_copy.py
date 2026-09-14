from datetime import datetime
from sqlmodel import Field, SQLModel
from app.models.base import utcnow


class WorkspaceCopy(SQLModel, table=True):
    __tablename__ = 'workspacecopy'
    request_id: str = Field(primary_key=True)
    source_workspace: str
    source_name: str
    source_paper_id: int
    source_updated_at: datetime
    paper_id: int = Field(foreign_key='paper.id', index=True)
    include_notes: bool = False
    pdf_sha256: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
