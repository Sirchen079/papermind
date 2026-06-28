from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Skill(SQLModel, table=True):
    __tablename__ = "skill"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str | None = None
    type: str = "instruction"  # instruction | template | tool | persona
    trigger: str = "manual"  # auto | keyword | manual | pipeline
    keywords_json: str = Field(default="[]")  # JSON list[str]
    model_role: str | None = None
    body: str | None = None  # markdown body
    enabled: bool = True
    source: str = "user"  # builtin | user
    file_path: str | None = None
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
