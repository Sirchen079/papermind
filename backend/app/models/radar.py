from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Subscription(SQLModel, table=True):
    """A saved arXiv watch query polled by the literature radar (P10.1).

    ``query_type`` selects how ``query_value`` is interpreted:
      - keyword: free-text search terms (e.g. "retrieval augmented generation")
      - category: an arXiv category (e.g. "cs.IR")
      - author: an author name (e.g. "J. Smith")

    ``last_run_at`` gates the opportunistic startup run: a subscription is due
    when its last run is older than 24h (or it has never run).
    """

    __tablename__ = "subscription"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    query_type: str  # keyword | category | author
    query_value: str
    max_results: int = 20
    lookback_days: int = 7
    enabled: bool = True
    last_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class RadarSeen(SQLModel, table=True):
    """One arXiv entry the radar has already surfaced (P10.2).

    Remembered forever so re-pulls never re-suggest an entry — even if it was
    skipped for being in the library already, or its suggestion was dismissed.
    ``arxiv_id`` is the natural unique key.
    """

    __tablename__ = "radarseen"
    arxiv_id: str = Field(primary_key=True)
    seen_date: datetime = Field(default_factory=utcnow, nullable=False)
