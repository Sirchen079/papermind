"""message_sources

Revision ID: d4e2b13caf55
Revises: c3f1a02b9e44
Create Date: 2026-06-29 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = "d4e2b13caf55"
down_revision = "c3f1a02b9e44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sources_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.drop_column("sources_json")
