"""Read the existing, editable paper notes across conversations."""
import json

from sqlalchemy import func
from sqlmodel import select

from app.models import Paper, PaperNote


def notes_catalog(session, paper_id, offset=0):
    offset = max(0, int(offset))
    total = session.exec(select(func.count(PaperNote.id)).where(PaperNote.paper_id == paper_id)).one()
    rows = session.exec(select(PaperNote).where(PaperNote.paper_id == paper_id)
                        .order_by(PaperNote.updated_at.desc(), PaperNote.id.desc())
                        .offset(offset).limit(20)).all()
    return {
        'total': total,
        'items': [{'note_id': row.id, 'kind': row.kind, 'version': row.version,
                   'preview': ' '.join(row.content.split())[:280],
                   'total_chars': len(row.content), 'updated_at': row.updated_at.isoformat(),
                   'read': {'tool': 'read_paper_notes', 'paper_id': paper_id, 'note_id': row.id}}
                  for row in rows],
        'next_offset': offset + len(rows) if offset + len(rows) < total else None,
    }


def read_paper_notes(session, paper_id, note_id=None, offset=0, start_char=0, max_chars=6000, version=None):
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        return json.dumps({'error': f'paper {paper_id} not found'})
    base = {'paper_id': paper.id, 'title': paper.title,
            'material_kind': 'research_record',
            'note': 'Saved editable research notes, not original paper text or proof of author claims. '
                    'Use their source locators to check original text when needed.'}
    if note_id is None:
        return json.dumps({**base, **notes_catalog(session, paper_id, offset)}, ensure_ascii=False)
    row = session.get(PaperNote, note_id)
    if row is None or row.paper_id != paper_id:
        return json.dumps({'error': 'note not found for this paper'})
    from app.reading.note_versions import read
    try: saved=read(session,paper_id,note_id,row.version if version is None else version)
    except LookupError:return json.dumps({'error':'note version not found'})
    content=saved['content']
    start = min(max(0, int(start_char)), len(content))
    end = min(len(content), start + max(500, min(int(max_chars), 12000)))
    return json.dumps({**base, 'type': 'note', 'note_id': row.id, 'kind': row.kind,
                       'kind':saved['kind'],'version':saved['version'],'current_version':row.version,
                       'text': content[start:end], 'total_chars': len(content),
                       'start_char': start, 'end_char': end,
                       'next_start_char': end if end < len(content) else None,
                       'next_read':{'tool':'read_paper_notes','paper_id':paper_id,'note_id':note_id,
                                    'version':saved['version'],'start_char':end} if end<len(content) else None,
                       'updated_at': saved['updated_at']}, ensure_ascii=False)
