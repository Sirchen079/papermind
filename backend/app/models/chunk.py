from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class PaperChunk(SQLModel, table=True):
    """A retrievable text chunk of a paper plus its embedding.

    The embedding is stored as a float32 little-endian BLOB (see app.rag.vector).
    ``embedding_model`` records which model produced the vector so retrieval can
    query only chunks compatible with the active embedding model — switching
    models (different dimensionality) simply requires re-indexing.
    """

    __tablename__ = "paperchunk"
    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    ordinal: int = 0  # position within the paper; 0 is the title+abstract chunk
    text: str
    embedding: bytes | None = None  # float32 blob
    embedding_model: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
