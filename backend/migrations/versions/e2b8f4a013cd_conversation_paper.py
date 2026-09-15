"""Keep the paper association when reopening a conversation."""
from alembic import op

revision = 'e2b8f4a013cd'
down_revision = 'd1a7e3f902bc'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite permits an inline nullable reference. Avoid table recreation:
    # it can reset the high-water ID after the latest conversation was deleted.
    op.execute('ALTER TABLE conversation ADD COLUMN paper_id INTEGER REFERENCES paper (id)')


def downgrade():
    op.drop_column('conversation', 'paper_id')
