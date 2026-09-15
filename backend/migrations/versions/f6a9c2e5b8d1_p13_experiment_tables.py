"""experiment / experimentlog / experimentpaperlink tables (P13 experiment log)

Revision ID: f6a9c2e5b8d1
Revises: c4e8f1a6b9d2
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a9c2e5b8d1"
down_revision = "c4e8f1a6b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("idea_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hypothesis", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["idea_id"], ["idea.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_experiment_project_id"), "experiment", ["project_id"], unique=False)
    op.create_index(op.f("ix_experiment_idea_id"), "experiment", ["idea_id"], unique=False)
    op.create_index(op.f("ix_experiment_status"), "experiment", ["status"], unique=False)

    op.create_table(
        "experimentlog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_experimentlog_experiment_id"), "experimentlog", ["experiment_id"], unique=False)

    op.create_table(
        "experimentpaperlink",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "paper_id", "role", name="uq_experimentpaperlink_exp_paper_role"),
    )
    op.create_index(
        op.f("ix_experimentpaperlink_experiment_id"),
        "experimentpaperlink",
        ["experiment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experimentpaperlink_paper_id"),
        "experimentpaperlink",
        ["paper_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_experimentpaperlink_paper_id"), table_name="experimentpaperlink")
    op.drop_index(op.f("ix_experimentpaperlink_experiment_id"), table_name="experimentpaperlink")
    op.drop_table("experimentpaperlink")
    op.drop_index(op.f("ix_experimentlog_experiment_id"), table_name="experimentlog")
    op.drop_table("experimentlog")
    op.drop_index(op.f("ix_experiment_status"), table_name="experiment")
    op.drop_index(op.f("ix_experiment_idea_id"), table_name="experiment")
    op.drop_index(op.f("ix_experiment_project_id"), table_name="experiment")
    op.drop_table("experiment")
