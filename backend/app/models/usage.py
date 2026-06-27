from datetime import date, datetime

from sqlmodel import SQLModel, Field

from app.models.base import utcnow


class TokenUsage(SQLModel, table=True):
    __tablename__ = "tokenusage"
    id: int | None = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="provider.id", index=True)
    model: str = Field(index=True)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_kind: str = Field(index=True)  # ingest | chat | skill | embed
    ref_id: str | None = None
    day: date = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class TokenUsageDaily(SQLModel, table=True):
    __tablename__ = "tokenusagedaily"
    day: date = Field(primary_key=True)
    provider_id: int = Field(primary_key=True)
    model: str = Field(primary_key=True)
    request_kind: str = Field(primary_key=True)
    total_tokens: int = 0
    call_count: int = 0
