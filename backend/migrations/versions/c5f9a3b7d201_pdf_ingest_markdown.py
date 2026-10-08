"""Remember import follow-ups while the PDF is transcribed in the background."""
from alembic import op
import sqlalchemy as sa

revision = 'c5f9a3b7d201'
down_revision = 'b4e8f2a6c9d1'
branch_labels = None
depends_on = None


def upgrade():
    if 'paperdocument' not in sa.inspect(op.get_bind()).get_table_names():
        # Minimal legacy databases acquire this optional table via create_all.
        return
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('paperdocument')}
    if 'followup_json' not in columns:
        op.add_column('paperdocument', sa.Column('followup_json', sa.String(), nullable=False, server_default='{}'))


def downgrade():
    with op.batch_alter_table('paperdocument') as batch:
        batch.drop_column('followup_json')
