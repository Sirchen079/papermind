"""analysisrun_error

Revision ID: e8b4f27c3a11
Revises: d4e2b13caf55
Create Date: 2026-06-29 01:00:00.000000

Add ``analysisrun.error`` so a failed AI analysis stores WHY it failed — the
detail view can then distinguish "never analyzed" from "analysis failed: <reason>"
instead of showing a generic "no summary".
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e8b4f27c3a11"
down_revision = "d4e2b13caf55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("analysisrun", schema=None) as batch_op:
        batch_op.add_column(sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("analysisrun", schema=None) as batch_op:
        batch_op.drop_column("error")
