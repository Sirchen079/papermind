from datetime import datetime
from sqlmodel import SQLModel, Field
from app.models.base import utcnow


class AIResultCache(SQLModel, table=True):
    """Validated research results, isolated inside the current library database."""
    __tablename__ = 'airesultcache'
    key: str = Field(primary_key=True)
    result_json: str
    created_at: datetime = Field(default_factory=utcnow, index=True)
