"""Never reuse a deleted conversation ID.

Revision ID: c8d1e4f7a902
Revises: b9d6a2e8f013
"""
from alembic import op

revision = "c8d1e4f7a902"
down_revision = "b9d6a2e8f013"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        "conversation", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ):
        pass


def downgrade():
    with op.batch_alter_table(
        "conversation", recreate="always", table_kwargs={"sqlite_autoincrement": False}
    ):
        pass
