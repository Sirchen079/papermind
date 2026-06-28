from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Conversation(SQLModel, table=True):
    __tablename__ = "conversation"
    id: int | None = Field(default=None, primary_key=True)
    title: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class Message(SQLModel, table=True):
    __tablename__ = "message"
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id", index=True)
    role: str  # user | assistant
    content: str
    model: str | None = None
    tokens_used: int | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
