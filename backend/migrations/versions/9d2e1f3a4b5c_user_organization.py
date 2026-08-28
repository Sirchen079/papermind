"""user organization

Revision ID: 9d2e1f3a4b5c
Revises: c5e6f7a8b9c0
Create Date: 2026-07-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9d2e1f3a4b5c"
down_revision = "c5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("user_created", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tag_name"), "tag", ["name"], unique=True)

    op.create_table(
        "collection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_collection_name"), "collection", ["name"], unique=True)

    op.create_table(
        "papertag",
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"]),
        sa.PrimaryKeyConstraint("paper_id", "tag_id"),
    )
    op.create_index(op.f("ix_papertag_paper_id"), "papertag", ["paper_id"], unique=False)
    op.create_index(op.f("ix_papertag_tag_id"), "papertag", ["tag_id"], unique=False)

    op.create_table(
        "collectionpaper",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collection.id"]),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("collection_id", "paper_id"),
    )
    op.create_index(
        op.f("ix_collectionpaper_collection_id"),
        "collectionpaper",
        ["collection_id"],
        unique=False,
    )
    op.create_index(op.f("ix_collectionpaper_paper_id"), "collectionpaper", ["paper_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_collectionpaper_paper_id"), table_name="collectionpaper")
    op.drop_index(op.f("ix_collectionpaper_collection_id"), table_name="collectionpaper")
    op.drop_table("collectionpaper")
    op.drop_index(op.f("ix_papertag_tag_id"), table_name="papertag")
    op.drop_index(op.f("ix_papertag_paper_id"), table_name="papertag")
    op.drop_table("papertag")
    op.drop_index(op.f("ix_collection_name"), table_name="collection")
    op.drop_table("collection")
    op.drop_index(op.f("ix_tag_name"), table_name="tag")
    op.drop_table("tag")
