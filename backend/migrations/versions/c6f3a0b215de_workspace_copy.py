"""Receipts for explicit, retry-safe paper copies between workspaces."""
from alembic import op
import sqlalchemy as sa

revision = 'c6f3a0b215de'
down_revision = 'b5e2f9a104cd'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('workspacecopy',
        sa.Column('request_id', sa.String(), primary_key=True),
        sa.Column('source_workspace', sa.String(), nullable=False),
        sa.Column('source_name', sa.String(), nullable=False),
        sa.Column('source_paper_id', sa.Integer(), nullable=False),
        sa.Column('source_updated_at', sa.DateTime(), nullable=False),
        sa.Column('paper_id', sa.Integer(), sa.ForeignKey('paper.id'), nullable=False),
        sa.Column('include_notes', sa.Boolean(), nullable=False),
        sa.Column('pdf_sha256', sa.String()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_workspacecopy_paper_id', 'workspacecopy', ['paper_id'])


def downgrade():
    op.drop_table('workspacecopy')
