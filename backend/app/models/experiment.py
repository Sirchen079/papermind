from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.base import utcnow

EXPERIMENT_STATUSES = ("planned", "running", "analyzing", "done", "abandoned")
EXPERIMENT_PAPER_ROLES = ("baseline", "method", "dataset")

# Lifecycle (P13.2): planned → running → analyzing → done/abandoned.
# Re- submitting the current status is a no-op, everything else is rejected
# with a structured error naming the allowed targets.
EXPERIMENT_TRANSITIONS = {
    ("planned", "running"),
    ("running", "analyzing"),
    ("analyzing", "done"),
    ("analyzing", "abandoned"),
}


class Experiment(SQLModel, table=True):
    """One recorded experiment, anchored to a project (required) and
    optionally to an idea, with baseline/method/dataset paper links."""

    __tablename__ = "experiment"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    idea_id: int | None = Field(default=None, foreign_key="idea.id", index=True)
    name: str
    hypothesis: str | None = None
    status: str = Field(default="planned", index=True)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    is_deleted: bool = False
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ExperimentLog(SQLModel, table=True):
    """An append-only timeline entry (markdown) for an experiment.

    Deliberately has no ``updated_at`` and no edit path — the timeline must
    stay truthful. Entries can be deleted, never rewritten.
    """

    __tablename__ = "experimentlog"

    id: int | None = Field(default=None, primary_key=True)
    experiment_id: int = Field(foreign_key="experiment.id", index=True)
    content: str
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class ExperimentPaperLink(SQLModel, table=True):
    """One paper serving one role (baseline/method/dataset) for an experiment.

    Unique (experiment_id, paper_id, role): the same paper may be both
    baseline and method, but never twice in the same role.
    """

    __tablename__ = "experimentpaperlink"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "paper_id", "role", name="uq_experimentpaperlink_exp_paper_role"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    experiment_id: int = Field(foreign_key="experiment.id", index=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    role: str
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
