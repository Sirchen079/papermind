"""reader last_page progress

Revision ID: b7d2e9f4c3a1
Revises: d8f3a1b2c4e5
"""

from alembic import op
import sqlalchemy as sa


revision = "b7d2e9f4c3a1"
down_revision = "d8f3a1b2c4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # P11.5: 内置阅读器记住每篇论文读到的页码，重开时恢复。
    op.add_column("paperreadingstate", sa.Column("last_page", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("paperreadingstate", "last_page")
