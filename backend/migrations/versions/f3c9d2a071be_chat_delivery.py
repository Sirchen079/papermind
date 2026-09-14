"""Retain failed chat turns and retry them without duplicating the question."""
from alembic import op
import sqlalchemy as sa

revision = 'f3c9d2a071be'
down_revision = 'e2b8f4a013cd'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('message', sa.Column('delivery_status', sa.String(), nullable=False, server_default='complete'))
    op.add_column('message', sa.Column('error_message', sa.Text(), nullable=True))
    op.add_column('message', sa.Column('request_json', sa.Text(), nullable=True))
    op.execute("""UPDATE message SET delivery_status='failed', error_message='上次回答未完成，可重新发送原问题。'
                  WHERE role='user' AND COALESCE((SELECT next.role FROM message AS next
                    WHERE next.conversation_id=message.conversation_id AND next.id>message.id
                    ORDER BY next.id LIMIT 1), 'user')='user'""")


def downgrade():
    op.drop_column('message', 'request_json')
    op.drop_column('message', 'error_message')
    op.drop_column('message', 'delivery_status')
