from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Report(SQLModel, table=True):
    """A stored LLM-generated group-meeting (weekly) report (P14.2).

    ``since``/``until`` are the aggregate window boundaries (naive UTC,
    ``[since 00:00, until+1d 00:00)``); ``content`` is Chinese markdown with
    the fixed section structure from the ``group-meeting-report`` template.
    """

    __tablename__ = "report"

    id: int | None = Field(default=None, primary_key=True)
    since: datetime
    until: datetime
    content: str
    model: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
