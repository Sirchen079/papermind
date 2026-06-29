from datetime import datetime

from sqlmodel import SQLModel, Field

from app.models.base import utcnow


class Provider(SQLModel, table=True):
    __tablename__ = "provider"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    type: str  # openai_chat | openai_responses | anthropic | openai_compat
    base_url: str | None = None
    api_key_encrypted: str | None = None
    extra_headers_json: str | None = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class Model(SQLModel, table=True):
    __tablename__ = "model"
    id: int | None = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="provider.id", index=True)
    model_id: str = Field(index=True)
    display_name: str | None = None
    context_window: int | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    role_default: str | None = None  # chat (default LLM: convo + summarize + extract) | embedding
    fetched_at: datetime | None = None
    is_manual: bool = False
