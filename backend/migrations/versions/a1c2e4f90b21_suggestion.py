"""suggestion

Revision ID: a1c2e4f90b21
Revises: 15bbb3981d6a
Create Date: 2026-06-28 17:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = "a1c2e4f90b21"
down_revision = "15bbb3981d6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suggestion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("detail_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=True),
        sa.Column("related_paper_id", sa.Integer(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("dedup_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.ForeignKeyConstraint(["related_paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("suggestion", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_suggestion_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_suggestion_dedup_key"), ["dedup_key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("suggestion", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_suggestion_dedup_key"))
        batch_op.drop_index(batch_op.f("ix_suggestion_status"))
    op.drop_table("suggestion")
