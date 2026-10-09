"""reviewmap: one literature map (themes + assignments) per review (A4a)."""

from alembic import op
import sqlalchemy as sa

revision = 'e8a1f4c6b9d2'
down_revision = 'd7b4c2e9f6a3'
branch_labels = None
depends_on = None


def upgrade():
    # 启动路径可能已 create_all 建表并 stamp：存在就跳过
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    names = set(inspector.get_table_names())
    indexes = {idx['name'] for idx in inspector.get_indexes('reviewmap')} if 'reviewmap' in names else set()
    if 'reviewmap' not in names:
        op.create_table(
            'reviewmap',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('review_id', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('stage', sa.String(), nullable=False),
            sa.Column('run_token', sa.String(), nullable=False),
            sa.Column('error', sa.String(), nullable=False),
            sa.Column('themes_json', sa.String(), nullable=False),
            sa.Column('themes_fingerprint', sa.String(), nullable=False),
            sa.Column('assignments_json', sa.String(), nullable=False),
            sa.Column('syntheses_json', sa.String(), nullable=False),
            sa.Column('overview_json', sa.String(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['review_id'], ['libraryreview.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    if 'ix_reviewmap_review_id' not in indexes:
        op.create_index(op.f('ix_reviewmap_review_id'), 'reviewmap', ['review_id'], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    names = set(inspector.get_table_names())
    if 'reviewmap' not in names:
        return
    indexes = {idx['name'] for idx in inspector.get_indexes('reviewmap')}
    if 'ix_reviewmap_review_id' in indexes:
        op.drop_index(op.f('ix_reviewmap_review_id'), table_name='reviewmap')
    op.drop_table('reviewmap')
