"""Immutable note snapshots; the existing note remains the current reading entry."""
import json
from sqlmodel import select
from app.models import PaperNoteRevision
from app.models.base import utc_iso


def snapshot(session, row):
    existing=session.exec(select(PaperNoteRevision).where(
        PaperNoteRevision.note_id==row.id, PaperNoteRevision.version==row.version)).first()
    if existing is None:
        session.add(PaperNoteRevision(note_id=row.id, **{key:getattr(row,key) for key in
            ('version','kind','content','tags_json','updated_at')}))


def read(session, paper_id, note_id, version):
    from app.reading.service import _owned_note
    note=_owned_note(session,paper_id,note_id)
    row=note if version==note.version else session.exec(select(PaperNoteRevision).where(
        PaperNoteRevision.note_id==note_id,PaperNoteRevision.version==version)).first()
    if row is None:raise LookupError('笔记版本不存在')
    from app.reviews.changes import comparison
    changes=[{k:c[k] for k in ('before','after')} for c in comparison(row.content,note.content)] if version!=note.version else []
    return {'note_id':note_id,'paper_id':paper_id,'current_version':note.version,
            'version':row.version,'kind':row.kind,'content':row.content,
            'tags':json.loads(row.tags_json),'updated_at':utc_iso(row.updated_at),
            'changes_to_current':changes}


def history(session,paper_id,note_id,offset=0):
    from app.reading.service import _owned_note
    note=_owned_note(session,paper_id,note_id)
    # Select metadata only: long paper cards must not all be loaded for a list.
    rows=session.exec(select(PaperNoteRevision.version,PaperNoteRevision.kind,PaperNoteRevision.updated_at)
        .where(PaperNoteRevision.note_id==note_id).order_by(PaperNoteRevision.version.desc()).offset(offset).limit(21)).all()
    if not rows and offset==0:rows=[(note.version,note.kind,note.updated_at)]
    return {'current_version':note.version,'items':[{'version':v,'kind':k,'updated_at':utc_iso(t)} for v,k,t in rows[:20]],
            'next_offset':offset+20 if len(rows)>20 else None}
