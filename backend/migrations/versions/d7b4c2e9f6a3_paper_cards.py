"""papercard: one paper-level structured reading card per paper (A2a)."""

from alembic import op
import sqlalchemy as sa

revision = 'd7b4c2e9f6a3'
down_revision = 'c5f9a3b7d201'
branch_labels = None
depends_on = None


def upgrade():
    # 启动路径可能已 create_all 建表并 stamp：存在就跳过
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    names = set(inspector.get_table_names())
    indexes = {idx['name'] for idx in inspector.get_indexes('papercard')} if 'papercard' in names else set()
    if 'papercard' not in names:
        op.create_table(
            'papercard',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('paper_id', sa.Integer(), nullable=False),
            sa.Column('fingerprint', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('card_json', sa.String(), nullable=False),
            sa.Column('model', sa.String(), nullable=True),
            sa.Column('warning', sa.String(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['paper_id'], ['paper.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    if 'ix_papercard_paper_id' not in indexes:
        op.create_index(op.f('ix_papercard_paper_id'), 'papercard', ['paper_id'], unique=True)
    if 'ix_papercard_fingerprint' not in indexes:
        op.create_index(op.f('ix_papercard_fingerprint'), 'papercard', ['fingerprint'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    names = set(inspector.get_table_names())
    if 'papercard' not in names:
        return
    indexes = {idx['name'] for idx in inspector.get_indexes('papercard')}
    if 'ix_papercard_fingerprint' in indexes:
        op.drop_index(op.f('ix_papercard_fingerprint'), table_name='papercard')
    if 'ix_papercard_paper_id' in indexes:
        op.drop_index(op.f('ix_papercard_paper_id'), table_name='papercard')
    op.drop_table('papercard')
