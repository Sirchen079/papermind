from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Conversation(SQLModel, table=True):
    __tablename__ = "conversation"
    # Late responses and other open windows must never target a reused ID.
    __table_args__ = {"sqlite_autoincrement": True}
    id: int | None = Field(default=None, primary_key=True)
    title: str | None = None
    paper_id: int | None = Field(default=None, foreign_key="paper.id")
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class Message(SQLModel, table=True):
    __tablename__ = "message"
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id", index=True)
    role: str  # user | assistant
    content: str
    model_context: str | None = None  # Immutable per-turn grounding; never UI text.
    delivery_status: str = Field(default="complete")  # user turn: pending / failed / complete
    error_message: str | None = None
    request_json: str | None = None  # Retry preserves this turn's selection and skills.
    clarification_json: str | None = None  # Assistant question card and durable response state.
    agent_state_json: str | None = None  # Private suspended/resumed tool history; never returned to UI.
    model: str | None = None
    tokens_used: int | None = None
    sources_json: str | None = None  # RAG provenance: [{paper_id, title, snippet}]
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
