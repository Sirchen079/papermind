"""Per-model capability fields: image support marker and thinking level.

Revision ID: b7e4f2a1c9d3
Revises: e815c2d437fa
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7e4f2a1c9d3'
down_revision = 'e815c2d437fa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('model', schema=None) as batch_op:
        batch_op.add_column(sa.Column('supports_images', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('reasoning_effort', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('model', schema=None) as batch_op:
        batch_op.drop_column('reasoning_effort')
        batch_op.drop_column('supports_images')
