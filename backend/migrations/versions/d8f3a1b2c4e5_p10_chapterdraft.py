"""chapterdraft table

Revision ID: d8f3a1b2c4e5
Revises: e1a4b7c9d2f6
"""

from alembic import op
import sqlalchemy as sa


revision = "d8f3a1b2c4e5"
down_revision = "e1a4b7c9d2f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chapterdraft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chapterdraft_chapter_id"), "chapterdraft", ["chapter_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chapterdraft_chapter_id"), table_name="chapterdraft")
    op.drop_table("chapterdraft")
