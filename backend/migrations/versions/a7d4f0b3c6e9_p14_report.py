"""report table (P14 group-meeting reports)

Revision ID: a7d4f0b3c6e9
Revises: f6a9c2e5b8d1
"""

from alembic import op
import sqlalchemy as sa


revision = "a7d4f0b3c6e9"
down_revision = "f6a9c2e5b8d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("since", sa.DateTime(), nullable=False),
        sa.Column("until", sa.DateTime(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("report")
