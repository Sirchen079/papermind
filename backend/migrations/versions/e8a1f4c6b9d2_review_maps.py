"""reviewmap: one literature map (themes + assignments) per review (A4a)."""

from alembic import op
import sqlalchemy as sa

revision = 'e8a1f4c6b9d2'
down_revision = 'd7b4c2e9f6a3'
branch_labels = None
depends_on = None


def upgrade():
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
    op.create_index(op.f('ix_reviewmap_review_id'), 'reviewmap', ['review_id'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_reviewmap_review_id'), table_name='reviewmap')
    op.drop_table('reviewmap')
