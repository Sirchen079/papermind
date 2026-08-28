"""thesis organization

Revision ID: ab4d5c6e7f8a
Revises: f2a9c1d4e6b8
Create Date: 2026-06-29 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "ab4d5c6e7f8a"
down_revision = "f2a9c1d4e6b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parent_project_id", sa.Integer(), nullable=True),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_parent_project_id"), "project", ["parent_project_id"], unique=False)

    op.create_table(
        "chapter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("parent_chapter_id", sa.Integer(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("outline", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_chapter_id"], ["chapter.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chapter_project_id"), "chapter", ["project_id"], unique=False)
    op.create_index(op.f("ix_chapter_parent_chapter_id"), "chapter", ["parent_chapter_id"], unique=False)

    op.create_table(
        "paperlink",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("chapter_id", sa.Integer(), nullable=True),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter.id"]),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paperlink_paper_id"), "paperlink", ["paper_id"], unique=False)
    op.create_index(op.f("ix_paperlink_project_id"), "paperlink", ["project_id"], unique=False)
    op.create_index(op.f("ix_paperlink_chapter_id"), "paperlink", ["chapter_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_paperlink_chapter_id"), table_name="paperlink")
    op.drop_index(op.f("ix_paperlink_project_id"), table_name="paperlink")
    op.drop_index(op.f("ix_paperlink_paper_id"), table_name="paperlink")
    op.drop_table("paperlink")

    op.drop_index(op.f("ix_chapter_parent_chapter_id"), table_name="chapter")
    op.drop_index(op.f("ix_chapter_project_id"), table_name="chapter")
    op.drop_table("chapter")

    op.drop_index(op.f("ix_project_parent_project_id"), table_name="project")
    op.drop_table("project")
