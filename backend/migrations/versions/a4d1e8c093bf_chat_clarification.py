"""Persist ask_user questions and the agent continuation across restarts."""
from alembic import op
import sqlalchemy as sa

revision = "a4d1e8c093bf"
down_revision = "f3c9d2a071be"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("message", sa.Column("clarification_json", sa.Text(), nullable=True))
    op.add_column("message", sa.Column("agent_state_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("message", "agent_state_json")
    op.drop_column("message", "clarification_json")
