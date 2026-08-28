"""paper citation key

Revision ID: c5e6f7a8b9c0
Revises: ab4d5c6e7f8a
Create Date: 2026-06-30 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "c5e6f7a8b9c0"
down_revision = "ab4d5c6e7f8a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper", sa.Column("citation_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f("ix_paper_citation_key"), "paper", ["citation_key"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_paper_citation_key"), table_name="paper")
    op.drop_column("paper", "citation_key")
