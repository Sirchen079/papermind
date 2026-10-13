"""paper.identity_status: mark PDF entries saved without a confirmed identity (R01)."""

from alembic import op
import sqlalchemy as sa

revision = 'b4c8e2f6a9d1'
down_revision = 'e8a1f4c6b9d2'
branch_labels = None
depends_on = None


def upgrade():
    # 启动路径可能已 create_all 建表并 stamp：存在就跳过
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'paper' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('paper')}
    if 'identity_status' not in columns:
        op.add_column('paper', sa.Column('identity_status', sa.String(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'paper' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('paper')}
    if 'identity_status' in columns:
        op.drop_column('paper', 'identity_status')
