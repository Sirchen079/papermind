"""Persist the source-list evidence used when recommending a candidate."""
from alembic import op
import sqlalchemy as sa

revision = 'f1030a1b2001'
down_revision = 'b4c8e2f6a9d1'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('literaturecandidate')}
    if 'source_quality' not in columns:
        op.add_column('literaturecandidate', sa.Column('source_quality', sa.String(), nullable=False, server_default=''))


def downgrade():
    op.drop_column('literaturecandidate', 'source_quality')
