"""reading workspace

Revision ID: f2a9c1d4e6b8
Revises: e8b4f27c3a11
Create Date: 2026-06-29 19:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f2a9c1d4e6b8"
down_revision = "e8b4f27c3a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paperreadingstate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("relevance", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_read_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paperreadingstate_paper_id"), "paperreadingstate", ["paper_id"], unique=True)
    op.create_index(op.f("ix_paperreadingstate_priority"), "paperreadingstate", ["priority"], unique=False)
    op.create_index(op.f("ix_paperreadingstate_relevance"), "paperreadingstate", ["relevance"], unique=False)
    op.create_index(op.f("ix_paperreadingstate_status"), "paperreadingstate", ["status"], unique=False)

    op.create_table(
        "papernote",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("tags_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_papernote_paper_id"), "papernote", ["paper_id"], unique=False)

    op.create_table(
        "paperexcerpt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("quote", sa.String(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("locator", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("tags_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paperexcerpt_paper_id"), "paperexcerpt", ["paper_id"], unique=False)

    op.create_table(
        "reviewmatrixentry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("problem", sa.String(), nullable=True),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("dataset", sa.String(), nullable=True),
        sa.Column("metrics", sa.String(), nullable=True),
        sa.Column("results", sa.String(), nullable=True),
        sa.Column("limitations", sa.String(), nullable=True),
        sa.Column("novelty", sa.String(), nullable=True),
        sa.Column("relation_to_thesis", sa.String(), nullable=True),
        sa.Column("future_work", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reviewmatrixentry_paper_id"), "reviewmatrixentry", ["paper_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_reviewmatrixentry_paper_id"), table_name="reviewmatrixentry")
    op.drop_table("reviewmatrixentry")
    op.drop_index(op.f("ix_paperexcerpt_paper_id"), table_name="paperexcerpt")
    op.drop_table("paperexcerpt")
    op.drop_index(op.f("ix_papernote_paper_id"), table_name="papernote")
    op.drop_table("papernote")
    op.drop_index(op.f("ix_paperreadingstate_status"), table_name="paperreadingstate")
    op.drop_index(op.f("ix_paperreadingstate_relevance"), table_name="paperreadingstate")
    op.drop_index(op.f("ix_paperreadingstate_priority"), table_name="paperreadingstate")
    op.drop_index(op.f("ix_paperreadingstate_paper_id"), table_name="paperreadingstate")
    op.drop_table("paperreadingstate")
