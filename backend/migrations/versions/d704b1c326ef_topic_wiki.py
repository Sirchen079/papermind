"""Versioned topic pages with retained evidence and explicit model updates."""
from alembic import op
import sqlalchemy as sa

revision = 'd704b1c326ef'
down_revision = 'c6f3a0b215de'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('wikipage',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('adopted_revision', sa.Integer()),
        sa.Column('archived', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_table('wikirevision',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('page_id', sa.String(), sa.ForeignKey('wikipage.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(), nullable=False),
        sa.Column('input_hash', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('evidence_json', sa.String(), nullable=False),
        sa.Column('references_json', sa.String(), nullable=False),
        sa.Column('support_status', sa.String(), nullable=False),
        sa.Column('review_note', sa.String(), nullable=False),
        sa.Column('origin', sa.String(), nullable=False),
        sa.Column('change_note', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('page_id', 'number'), sa.UniqueConstraint('page_id', 'request_id'))
    op.create_index('ix_wikirevision_page_id', 'wikirevision', ['page_id'])
    op.create_table('wikiupdate',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('page_id', sa.String(), sa.ForeignKey('wikipage.id'), nullable=False),
        sa.Column('base_version', sa.Integer(), nullable=False),
        sa.Column('request_hash', sa.String(), nullable=False),
        sa.Column('inputs_json', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('result_json', sa.String()),
        sa.Column('revision_number', sa.Integer()),
        sa.Column('error', sa.String()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_wikiupdate_page_id', 'wikiupdate', ['page_id'])


def downgrade():
    op.drop_table('wikiupdate')
    op.drop_table('wikirevision')
    op.drop_table('wikipage')
