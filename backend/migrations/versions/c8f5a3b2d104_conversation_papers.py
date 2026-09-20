"""Persist the selected paper set for a conversation."""
from alembic import op
import sqlalchemy as sa

revision = 'c8f5a3b2d104'
down_revision = 'b7e4f2a1c9d3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversation', sa.Column('paper_ids_json', sa.String(), nullable=False, server_default='[]'))


def downgrade():
    # Avoid rebuilding conversation: preserve AUTOINCREMENT and the original
    # inline paper_id FK used by the earlier single-paper migration.
    op.drop_column('conversation', 'paper_ids_json')
