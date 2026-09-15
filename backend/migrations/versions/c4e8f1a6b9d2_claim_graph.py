"""claim / claimrelation tables (P12 Claim-Evidence graph)

Revision ID: c4e8f1a6b9d2
Revises: b7d2e9f4c3a1
"""

from alembic import op
import sqlalchemy as sa


revision = "c4e8f1a6b9d2"
down_revision = "b7d2e9f4c3a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("excerpt_id", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.ForeignKeyConstraint(["excerpt_id"], ["paperexcerpt.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_claim_paper_id"), "claim", ["paper_id"], unique=False)

    op.create_table(
        "claimrelation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("claim_a_id", sa.Integer(), nullable=False),
        sa.Column("claim_b_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["claim_a_id"], ["claim.id"]),
        sa.ForeignKeyConstraint(["claim_b_id"], ["claim.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_a_id", "claim_b_id", "type", name="uq_claimrelation_a_b_type"),
    )
    op.create_index(op.f("ix_claimrelation_claim_a_id"), "claimrelation", ["claim_a_id"], unique=False)
    op.create_index(op.f("ix_claimrelation_claim_b_id"), "claimrelation", ["claim_b_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_claimrelation_claim_b_id"), table_name="claimrelation")
    op.drop_index(op.f("ix_claimrelation_claim_a_id"), table_name="claimrelation")
    op.drop_table("claimrelation")
    op.drop_index(op.f("ix_claim_paper_id"), table_name="claim")
    op.drop_table("claim")
