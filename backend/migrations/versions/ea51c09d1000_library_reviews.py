"""Library reviews with independent, resumable checkpoints."""
from alembic import op
from app.models.review import LibraryReview, ReviewPaper, ReviewSection, ReviewRevision

revision = 'ea51c09d1000'
down_revision = 'd9a6c4e3b215'
branch_labels = None
depends_on = None


def upgrade():
    for model in (LibraryReview, ReviewPaper, ReviewSection, ReviewRevision):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for model in (ReviewRevision, ReviewSection, ReviewPaper, LibraryReview):
        model.__table__.drop(op.get_bind())
