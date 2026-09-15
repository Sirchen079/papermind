"""subscription + radarseen tables

Revision ID: e1a4b7c9d2f6
Revises: c3a7e8f2b5d9
"""

from alembic import op
import sqlalchemy as sa


revision = "e1a4b7c9d2f6"
down_revision = "c3a7e8f2b5d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("query_type", sa.String(), nullable=False),
        sa.Column("query_value", sa.String(), nullable=False),
        sa.Column("max_results", sa.Integer(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "radarseen",
        sa.Column("arxiv_id", sa.String(), nullable=False),
        sa.Column("seen_date", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("arxiv_id"),
    )
    op.create_index(op.f("ix_radarseen_arxiv_id"), "radarseen", ["arxiv_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_radarseen_arxiv_id"), table_name="radarseen")
    op.drop_table("radarseen")
    op.drop_table("subscription")
