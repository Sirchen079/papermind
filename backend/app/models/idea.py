from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.base import utcnow

IDEA_STATUSES = ("proposed", "refining", "testing", "adopted", "dropped")
IDEA_PRIORITIES = ("low", "normal", "high")
IDEA_ORIGINS = ("manual", "matrix", "suggestion", "gap")
IDEA_PAPER_ROLES = ("basis", "contrast", "support")

# Lifecycle: proposed → refining → testing → adopted/dropped, plus the cheap
# kill proposed → dropped. Anything else is rejected with a structured error.
IDEA_TRANSITIONS = {
    ("proposed", "refining"),
    ("refining", "testing"),
    ("testing", "adopted"),
    ("testing", "dropped"),
    ("proposed", "dropped"),
}


class Idea(SQLModel, table=True):
    """A research idea with a lifecycle, evidence papers, and a project anchor."""

    __tablename__ = "idea"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    content: str = ""  # markdown
    hypothesis: str | None = None
    status: str = Field(default="proposed", index=True)
    priority: str = Field(default="normal", index=True)
    origin: str = Field(default="manual", index=True)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    is_deleted: bool = False
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
    closed_at: datetime | None = None


class IdeaPaperLink(SQLModel, table=True):
    """One paper serving one evidence role for one idea.

    Unique (idea_id, paper_id, role): the same paper may be both basis and
    contrast for an idea, but never twice in the same role.
    """

    __tablename__ = "ideapaperlink"
    __table_args__ = (
        UniqueConstraint("idea_id", "paper_id", "role", name="uq_ideapaperlink_idea_paper_role"),
    )

    id: int | None = Field(default=None, primary_key=True)
    idea_id: int = Field(foreign_key="idea.id", index=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    role: str
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
