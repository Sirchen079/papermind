"""Record provider cache usage and persist validated research step reuse."""
from alembic import op
import sqlalchemy as sa

revision = 'c6f1a8b3d092'
down_revision = 'c8d1e4f7a902'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tokenusage', sa.Column('cached_input_tokens', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tokenusage', sa.Column('cache_write_tokens', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('tokenusage', sa.Column('cache_usage_reported', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('airesultcache', sa.Column('key', sa.String(), primary_key=True), sa.Column('result_json', sa.Text(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_airesultcache_created_at', 'airesultcache', ['created_at'])


def downgrade():
    op.drop_table('airesultcache')
    op.drop_column('tokenusage', 'cache_usage_reported')
    op.drop_column('tokenusage', 'cache_write_tokens')
    op.drop_column('tokenusage', 'cached_input_tokens')
