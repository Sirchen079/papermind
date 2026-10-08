"""Read adjacent indexed passages without changing stored chunks or ranking."""
import re
from types import SimpleNamespace
from sqlalchemy import tuple_
from sqlmodel import select
from app.models import Paper, PaperChunk


PAGE=re.compile(r'^\[第 (\d+) 页\]\n')


def with_context(session, chunks):
    if not chunks:return []
    keys={(c.paper_id,n) for c in chunks for n in (c.ordinal-1,c.ordinal,c.ordinal+1) if n>=0}
    rows=session.exec(select(PaperChunk).join(Paper).where(Paper.is_deleted==False,
        tuple_(PaperChunk.paper_id,PaperChunk.ordinal).in_(keys))).all()
    by_key={(r.paper_id,r.ordinal):r for r in rows}
    result=[]
    for chunk in chunks:
        current=by_key.get((chunk.paper_id,chunk.ordinal))
        # Reindexing can replace a previously retrieved anchor. Do not join old
        # text to new neighbors; the caller can still use its original evidence.
        if current is None or current.text!=chunk.text:
            result.append(chunk);continue
        paged=bool(PAGE.match(chunk.text))
        if chunk.ordinal==0 and not paged:
            result.append(chunk);continue
        segments=[]
        for n in (chunk.ordinal-1,chunk.ordinal,chunk.ordinal+1):
            row=by_key.get((chunk.paper_id,n))
            if row is None or row.embedding_model!=current.embedding_model:continue
            page=PAGE.match(row.text)
            if paged and not page:continue
            if not paged and n==0:continue  # Metadata is not preceding prose.
            segments.append(dict(ordinal=n,page=int(page[1]) if page else None,quote=row.text))
        if len(segments)<2:
            result.append(chunk);continue
        # Keep the exact excerpts separately so saved sources retain each page.
        # Keep the anchor first when a small writing window has to clip context.
        text=chunk.text
        for n,label in ((chunk.ordinal+1,'后续原文'),(chunk.ordinal-1,'前文')):
            neighbor=next((s for s in segments if s['ordinal']==n),None)
            if neighbor:text+=f'\n\n[{label}]\n'+neighbor['quote']
        result.append(SimpleNamespace(id=chunk.id,paper_id=chunk.paper_id,ordinal=chunk.ordinal,
            text=text,anchor_text=chunk.text,context_segments=segments))
    return result
