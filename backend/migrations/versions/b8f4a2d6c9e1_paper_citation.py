"""paper citation

Revision ID: b8f4a2d6c9e1
Revises: 9d2e1f3a4b5c
"""

from alembic import op
import sqlalchemy as sa


revision = "b8f4a2d6c9e1"
down_revision = "9d2e1f3a4b5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "papercitation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_paper_id", sa.Integer(), nullable=False),
        sa.Column("target_paper_id", sa.Integer(), nullable=True),
        sa.Column("raw_ref", sa.String(), nullable=False),
        sa.Column("ref_title", sa.String(), nullable=True),
        sa.Column("ref_title_norm", sa.String(), nullable=True),
        sa.Column("ref_doi", sa.String(), nullable=True),
        sa.Column("ref_arxiv_id", sa.String(), nullable=True),
        sa.Column("ref_year", sa.Integer(), nullable=True),
        sa.Column("ref_authors_json", sa.String(), nullable=False),
        sa.Column("match_status", sa.String(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_paper_id"], ["paper.id"]),
        sa.ForeignKeyConstraint(["target_paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_paper_id", "ref_title_norm", name="uq_papercitation_source_titlenorm"),
    )
    op.create_index(op.f("ix_papercitation_source_paper_id"), "papercitation", ["source_paper_id"], unique=False)
    op.create_index(op.f("ix_papercitation_target_paper_id"), "papercitation", ["target_paper_id"], unique=False)
    op.create_index(op.f("ix_papercitation_ref_title_norm"), "papercitation", ["ref_title_norm"], unique=False)
    op.create_index(op.f("ix_papercitation_ref_doi"), "papercitation", ["ref_doi"], unique=False)
    op.create_index(op.f("ix_papercitation_ref_arxiv_id"), "papercitation", ["ref_arxiv_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_papercitation_ref_arxiv_id"), table_name="papercitation")
    op.drop_index(op.f("ix_papercitation_ref_doi"), table_name="papercitation")
    op.drop_index(op.f("ix_papercitation_ref_title_norm"), table_name="papercitation")
    op.drop_index(op.f("ix_papercitation_target_paper_id"), table_name="papercitation")
    op.drop_index(op.f("ix_papercitation_source_paper_id"), table_name="papercitation")
    op.drop_table("papercitation")
