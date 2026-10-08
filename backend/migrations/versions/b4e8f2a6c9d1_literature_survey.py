"""Literature survey tables: AI-assisted discovery with human selection."""
from alembic import op
import sqlalchemy as sa


revision = 'b4e8f2a6c9d1'
down_revision = 'f0830c1d3002'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    names = set(sa.inspect(bind).get_table_names())
    if 'literaturesurvey' not in names:
        op.create_table(
            'literaturesurvey',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('query', sa.String(), nullable=False),
            sa.Column('years', sa.Integer(), nullable=False, server_default='2'),
            sa.Column('max_results', sa.Integer(), nullable=False, server_default='20'),
            sa.Column('status', sa.String(), nullable=False, server_default='queued'),
            sa.Column('error', sa.String(), nullable=False, server_default=''),
            sa.Column('expansion_used', sa.String(), nullable=False, server_default='[]'),
            sa.Column('screened', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('import_status', sa.String(), nullable=False, server_default='idle'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('finished_at', sa.DateTime(), nullable=True),
        )
    if 'literaturecandidate' not in names:
        op.create_table(
            'literaturecandidate',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('survey_id', sa.Integer(),
                      sa.ForeignKey('literaturesurvey.id'), nullable=False, index=True),
            sa.Column('openalex_id', sa.String(), nullable=False, server_default=''),
            sa.Column('doi', sa.String(), nullable=False, server_default=''),
            sa.Column('arxiv_id', sa.String(), nullable=False, server_default=''),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('year', sa.Integer(), nullable=True),
            sa.Column('venue', sa.String(), nullable=False, server_default=''),
            sa.Column('authors_json', sa.String(), nullable=False, server_default='[]'),
            sa.Column('cited_by_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('oa_pdf_url', sa.String(), nullable=False, server_default=''),
            sa.Column('abstract', sa.String(), nullable=False, server_default=''),
            sa.Column('relevance', sa.String(), nullable=False, server_default=''),
            sa.Column('keep', sa.Boolean(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='candidate'),
            sa.Column('paper_id', sa.Integer(), nullable=True),
            sa.Column('note', sa.String(), nullable=False, server_default=''),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table('literaturecandidate')
    op.drop_table('literaturesurvey')
