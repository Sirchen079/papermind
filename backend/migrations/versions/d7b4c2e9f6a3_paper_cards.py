"""papercard: one paper-level structured reading card per paper (A2a)."""

from alembic import op
import sqlalchemy as sa

revision = 'd7b4c2e9f6a3'
down_revision = 'c5f9a3b7d201'
branch_labels = None
depends_on = None


def upgrade():
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
    op.create_index(op.f('ix_papercard_paper_id'), 'papercard', ['paper_id'], unique=True)
    op.create_index(op.f('ix_papercard_fingerprint'), 'papercard', ['fingerprint'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_papercard_fingerprint'), table_name='papercard')
    op.drop_index(op.f('ix_papercard_paper_id'), table_name='papercard')
    op.drop_table('papercard')
