"""Add isolated research tasks, versioned judgments and explicit reuse."""
from alembic import op
import sqlalchemy as sa

revision = 'b9d6a2e8f013'
down_revision = 'a7d4f0b3c6e9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('researchtask',
        sa.Column('id',sa.String(),primary_key=True),
        sa.Column('question',sa.Text(),nullable=False),
        sa.Column('project_id',sa.Integer(),sa.ForeignKey('project.id'),nullable=True),
        sa.Column('depth',sa.String(),nullable=False),
        sa.Column('paper_ids_json',sa.Text(),nullable=False),
        sa.Column('materials_json',sa.Text(),nullable=False),
        sa.Column('steps_json',sa.Text(),nullable=False),
        sa.Column('status',sa.String(),nullable=False),
        sa.Column('stop_reason',sa.String(),nullable=True),
        sa.Column('run_token',sa.String(),nullable=True),
        sa.Column('error',sa.Text(),nullable=True),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_table('researchartifact',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('task_id',sa.String(),sa.ForeignKey('researchtask.id'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('content',sa.Text(),nullable=False),
        sa.Column('evidence_refs_json',sa.Text(),nullable=False),
        sa.Column('evidence_snapshot_json',sa.Text(),nullable=False),
        sa.Column('claim_kind',sa.String(),nullable=False),
        sa.Column('support_status',sa.String(),nullable=False),
        sa.Column('review_note',sa.Text(),nullable=False),
        sa.Column('adopted',sa.Boolean(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('task_id','version'))
    op.create_index('ix_researchartifact_task_id','researchartifact',['task_id'])
    op.create_table('researchreuse',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('task_id',sa.String(),sa.ForeignKey('researchtask.id'),nullable=False),
        sa.Column('artifact_id',sa.Integer(),sa.ForeignKey('researchartifact.id'),nullable=False),
        sa.Column('kind',sa.String(),nullable=False),
        sa.Column('content',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('task_id','kind'))
    op.create_index('ix_researchreuse_task_id','researchreuse',['task_id'])


def downgrade():
    op.drop_table('researchreuse')
    op.drop_table('researchartifact')
    op.drop_table('researchtask')
