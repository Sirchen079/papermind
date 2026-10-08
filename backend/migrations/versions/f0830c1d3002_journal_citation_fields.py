"""Retain journal volume, issue and page/article locators."""
from alembic import op
import sqlalchemy as sa

revision = 'f0830c1d3002'
down_revision = 'f0718b9c2001'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('paper')}
    for name in ('volume', 'issue', 'pages'):
        if name not in columns:
            op.add_column('paper', sa.Column(name, sa.String(), nullable=True))


def downgrade():
    for name in ('pages', 'issue', 'volume'):
        op.drop_column('paper', name)
