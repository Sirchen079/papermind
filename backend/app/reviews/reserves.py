"""Task-local output allowances shared by generation and paragraph proposals."""
import hashlib
import json
from sqlmodel import Session, select
from sqlalchemy.exc import SQLAlchemyError
from app.models.review import LibraryReview, ReviewSection
from app.providers.client import DEFAULT_REASONING_EFFORT

ORDINAL = -99995
FINGERPRINT = 'review-output-reserves-v1'


def model_key(provider, model, window, effort):
    value=[provider.id,getattr(provider,'base_url',''),model,window,effort or DEFAULT_REASONING_EFFORT]
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()


def _row(session, review_id):
    return session.exec(select(ReviewSection).where(
        ReviewSection.review_id==review_id,ReviewSection.ordinal==ORDINAL)).first()


def _values(row):
    if row is None or row.fingerprint!=FINGERPRINT or row.warning:return {}
    try:
        values=json.loads(row.content)
        return {k:v for k,v in values.items() if type(v) is int and v>=0} if isinstance(values,dict) else {}
    except (ValueError,TypeError):return {}


def load(session, review_id):
    return _values(_row(session,review_id))


def increase(engine, review_id, key, value, run_token=None):
    """Merge under a short write lock; a late response never resurrects a task."""
    try:
        with Session(engine) as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            review=session.get(LibraryReview,review_id)
            if review is None or (run_token is not None and review.run_token!=run_token):return value
            row=_row(session,review_id);values=_values(row)
            values[key]=max(value,values.get(key,0))
            if row is None:row=ReviewSection(review_id=review_id,ordinal=ORDINAL,title='模型输出额度')
            row.fingerprint=FINGERPRINT;row.content=json.dumps(values,sort_keys=True);row.warning=''
            session.add(row);session.commit()
            return values[key]
    except SQLAlchemyError:
        # This is a performance hint. An unavailable checkpoint must not throw
        # away a usable proposal or prevent the already allowed retry.
        return value
