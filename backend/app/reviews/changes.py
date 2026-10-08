"""Published change records and version comparisons, using existing revisions."""
import json
import re
from difflib import SequenceMatcher
from fastapi import HTTPException
from sqlmodel import select
from app.models.review import ReviewRevision, ReviewSection
from app.reviews import service, editing, continuation

BASE = -400000


def save(session, job, previous_version, changes, evidence):
    cited={int(pid) for c in changes for pid in re.findall(r'\[P(\d+)\]',c['before']+c['after'])}
    sources=[];seen=set()
    for e in evidence:
        key=(e.get('paper_id'),e.get('quote'))
        if key[0] in cited and key not in seen:
            seen.add(key);sources.append(e)
    data={'base_version':previous_version,'version':job.version,'changes':changes,
          'body_hash':service.digest(continuation.body(job.content))}
    session.add(ReviewSection(review_id=job.id,ordinal=BASE-job.version,title='已发布的局部修改',
        fingerprint=service.digest(data),content=service.encode(data),evidence_json=service.encode(sources)))


def comparison(before,after):
    left=editing.blocks(before,0);right=editing.blocks(after,0);result=[]
    for kind,a,b,c,d in SequenceMatcher(None,[x['text'] for x in left],[x['text'] for x in right],autojunk=False).get_opcodes():
        if kind=='equal':continue
        # Pair replacements when the paragraph counts agree; otherwise retain
        # an exact contiguous span so insertions/deletions remain legible.
        pairs=[(a+i,a+i+1,c+i,c+i+1) for i in range(b-a)] if kind=='replace' and b-a==d-c else [(a,b,c,d)]
        for a1,b1,c1,d1 in pairs:
            start=right[c1]['start'] if c1<d1 else None
            end=right[d1-1]['end'] if c1<d1 else None
            result.append({'before':before[left[a1]['start']:left[b1-1]['end']] if a1<b1 else '',
                           'after':after[start:end] if start is not None else '',
                           'reason':'','start':start,'end':end})
    return result


def read(session,review_id,version):
    job=service.get(session,review_id)
    target=session.exec(select(ReviewRevision).where(ReviewRevision.review_id==review_id,ReviewRevision.version==version)).first()
    if target is None:raise LookupError('历史版本不存在')
    prior=session.exec(select(ReviewRevision).where(ReviewRevision.review_id==review_id,ReviewRevision.version<version).order_by(ReviewRevision.version.desc())).first()
    saved=session.exec(select(ReviewSection).where(ReviewSection.review_id==review_id,ReviewSection.ordinal==BASE-version)).first()
    evidence=[];snapshot=False
    if saved:
        data=json.loads(saved.content);items=data['changes'];base_version=data['base_version'];evidence=json.loads(saved.evidence_json);snapshot=True
        body=continuation.body(target.content);offset=target.content.find(body)
        for item in items:
            item['start']=offset+item['after_start'] if service.digest(body)==data['body_hash'] else None
            item['end']=item['start']+len(item['after']) if item['start'] is not None else None
    else:
        base_version=prior.version if prior else 0;items=comparison(prior.content if prior else '',target.content)
    current=editing.blocks(job.content,job.version)
    from app.agent.document_edits import _unchanged_span
    for i,item in enumerate(items):
        item['id']=str(i);item['paper_ids']=list(dict.fromkeys(int(pid) for pid in re.findall(r'\[P(\d+)\]',item['before']+item['after'])))
        item['current_block_id']=None
        if item['start'] is not None and item['after']:
            try:
                start,end=_unchanged_span(target.content,job.content,item['start'],item['end'])
                block=next((b for b in current if b['start']==start and b['end']==end and b['text']==item['after']),None)
                if block:item['current_block_id']=block['id']
            except HTTPException:pass
        item.pop('start',None);item.pop('end',None)
    return {'version':version,'base_version':base_version,'current_version':job.version,
            'snapshot':snapshot,'changes':items,'evidence':evidence}
