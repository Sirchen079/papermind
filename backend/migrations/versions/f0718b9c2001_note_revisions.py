"""Preserve research-note corrections without changing note identities."""
from alembic import op
import sqlalchemy as sa
from app.models.reading import PaperNoteRevision

revision = 'f0718b9c2001'
down_revision = 'ea51c09d1000'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if 'version' not in {c['name'] for c in sa.inspect(bind).get_columns('papernote')}:
        op.add_column('papernote', sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    PaperNoteRevision.__table__.create(bind, checkfirst=True)
    bind.execute(sa.text('''INSERT INTO papernoterevision (note_id,version,kind,content,tags_json,updated_at)
        SELECT n.id,n.version,n.kind,n.content,n.tags_json,n.updated_at FROM papernote n
        WHERE NOT EXISTS (SELECT 1 FROM papernoterevision r WHERE r.note_id=n.id AND r.version=n.version)'''))


def downgrade():
    PaperNoteRevision.__table__.drop(op.get_bind())
    op.drop_column('papernote', 'version')
