from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Tag(SQLModel, table=True):
    __tablename__ = "tag"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    color: str | None = None
    user_created: bool = True
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class PaperTag(SQLModel, table=True):
    __tablename__ = "papertag"
    paper_id: int = Field(foreign_key="paper.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class Collection(SQLModel, table=True):
    __tablename__ = "collection"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class CollectionPaper(SQLModel, table=True):
    __tablename__ = "collectionpaper"
    collection_id: int = Field(foreign_key="collection.id", primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", primary_key=True)
    added_at: datetime = Field(default_factory=utcnow, nullable=False)
