"""Durable page transcription and Markdown artifacts."""
from alembic import op
import sqlalchemy as sa

revision = 'd9a6c4e3b215'
down_revision = 'c8f5a3b2d104'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('paperdocument',
        sa.Column('paper_id', sa.Integer(), sa.ForeignKey('paper.id', ondelete='CASCADE'), primary_key=True),
        *[sa.Column(name, sa.String(), nullable=False, server_default=default) for name, default in [
            ('run_id', ''), ('source_hash', ''), ('status', 'idle'), ('mode', 'auto'),
            ('model_name', ''), ('pages_json', '[]'), ('markdown', ''), ('published_hash', ''),
            ('error', ''), ('index_status', '')]],
        sa.Column('model_config_id', sa.Integer(), nullable=True),
        sa.Column('total_pages', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade():
    op.drop_table('paperdocument')
