"""Provenance and retry receipts for independent topic snapshots."""
from alembic import op
import sqlalchemy as sa

revision = 'e815c2d437fa'
down_revision = 'd704b1c326ef'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('wikicopy',
        sa.Column('request_id', sa.String(), primary_key=True),
        sa.Column('source_workspace', sa.String(), nullable=False),
        sa.Column('source_name', sa.String(), nullable=False),
        sa.Column('source_page_id', sa.String(), nullable=False),
        sa.Column('source_revision', sa.Integer(), nullable=False),
        sa.Column('source_title', sa.String(), nullable=False),
        sa.Column('page_id', sa.String(), sa.ForeignKey('wikipage.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_wikicopy_page_id', 'wikicopy', ['page_id'])


def downgrade():
    op.drop_table('wikicopy')
