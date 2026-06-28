"""paperchunk

Revision ID: c3f1a02b9e44
Revises: a1c2e4f90b21
Create Date: 2026-06-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = "c3f1a02b9e44"
down_revision = "a1c2e4f90b21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paperchunk",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("paperchunk", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paperchunk_paper_id"), ["paper_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_paperchunk_embedding_model"), ["embedding_model"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("paperchunk", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_paperchunk_embedding_model"))
        batch_op.drop_index(batch_op.f("ix_paperchunk_paper_id"))
    op.drop_table("paperchunk")
