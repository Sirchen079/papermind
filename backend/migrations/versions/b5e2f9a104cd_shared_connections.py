"""Project references to shared model connections and durable provider history."""
from alembic import op
import sqlalchemy as sa

revision='b5e2f9a104cd'
down_revision='a4d1e8c093bf'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('provider',sa.Column('is_deleted',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('provider',sa.Column('shared_connection_id',sa.String(),nullable=True))


def downgrade():
    op.drop_column('provider','shared_connection_id')
    op.drop_column('provider','is_deleted')
