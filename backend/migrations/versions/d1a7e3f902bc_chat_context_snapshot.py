"""Persist per-turn grounding so conversation prefixes remain stable."""
from alembic import op
import sqlalchemy as sa

revision = 'd1a7e3f902bc'
down_revision = 'c6f1a8b3d092'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('message', sa.Column('model_context', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('message', 'model_context')
