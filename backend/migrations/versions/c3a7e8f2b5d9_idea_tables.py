"""idea + ideapaperlink tables

Revision ID: c3a7e8f2b5d9
Revises: b8f4a2d6c9e1
"""

from alembic import op
import sqlalchemy as sa


revision = "c3a7e8f2b5d9"
down_revision = "b8f4a2d6c9e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idea",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("hypothesis", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_idea_status"), "idea", ["status"], unique=False)
    op.create_index(op.f("ix_idea_priority"), "idea", ["priority"], unique=False)
    op.create_index(op.f("ix_idea_origin"), "idea", ["origin"], unique=False)
    op.create_index(op.f("ix_idea_project_id"), "idea", ["project_id"], unique=False)

    op.create_table(
        "ideapaperlink",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idea_id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["idea_id"], ["idea.id"]),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idea_id", "paper_id", "role", name="uq_ideapaperlink_idea_paper_role"),
    )
    op.create_index(op.f("ix_ideapaperlink_idea_id"), "ideapaperlink", ["idea_id"], unique=False)
    op.create_index(op.f("ix_ideapaperlink_paper_id"), "ideapaperlink", ["paper_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ideapaperlink_paper_id"), table_name="ideapaperlink")
    op.drop_index(op.f("ix_ideapaperlink_idea_id"), table_name="ideapaperlink")
    op.drop_table("ideapaperlink")
    op.drop_index(op.f("ix_idea_project_id"), table_name="idea")
    op.drop_index(op.f("ix_idea_origin"), table_name="idea")
    op.drop_index(op.f("ix_idea_priority"), table_name="idea")
    op.drop_index(op.f("ix_idea_status"), table_name="idea")
    op.drop_table("idea")
