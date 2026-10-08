"""Retrieve original context for claims in a draft, without gating its output."""
import hashlib
import re
from app.research.materials import terms
from app.reviews.evidence import candidates


NUMBER=re.compile(r'(?<![A-Za-z0-9_.])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,}|\d+(?=\s*[%％]))(?![A-Za-z0-9_.])')
STOP={'the','and','for','with','from','this','that','are','was','were','has','have','not','only','than','their','using'}


def numbers(text):
    return {m[0].replace(',','') for m in NUMBER.finditer(text)}


def cited_claims(paragraph):
    ids=list(dict.fromkeys(int(x) for x in re.findall(r'\[P(\d+)\]',paragraph)))
    if len(ids)<2:return {pid:[paragraph] for pid in ids}
    # A citation may follow punctuation, and decimal points are not sentence
    # boundaries. Keep uncited setup with the next cited unit; retain a final
    # continuation with the last source. Shared citations keep shared context.
    units=[];start=0
    for boundary in re.finditer(r'[。！？；;]|[.!?](?=\s|$|\[P\d+\])',paragraph):
        if boundary.start()<start:continue
        end=boundary.end()
        if not re.search(r'\[P\d+\]',paragraph[start:end]):
            suffix=re.match(r'(?:\s*\[P\d+\])+',paragraph[end:])
            if suffix:end+=suffix.end()
        units.append(paragraph[start:end]);start=end
    if start<len(paragraph):units.append(paragraph[start:])
    result={};pending=[];last=[]
    for unit in units:
        pending.append(unit)
        cited=list(dict.fromkeys(int(x) for x in re.findall(r'\[P(\d+)\]',unit)))
        if not cited:continue
        claim=''.join(pending).strip();pending=[]
        for pid in cited:result.setdefault(pid,[]).append(claim)
        last=cited
    if pending and last:
        for pid in last:result[pid][-1]+=''.join(pending)
    return {pid:result.get(pid,[paragraph]) for pid in ids}


def score(text, claim):
    numeric=numbers(text)&numbers(claim)
    lexical=(terms(text)&terms(re.sub(r'\[P\d+\]','',claim)))-STOP
    return len(numeric)*12+min(10,len(lexical)) if numeric or len(lexical)>=2 else 0


def text_matches(full, claims, limit=3):
    spans=[s for s in candidates(full,2400) if s['region']!='references']
    selected=[]
    for claim in claims:
        ranked=sorted(spans,key=lambda s:score(s['quote'],claim),reverse=True)
        match=next((s for s in ranked if s['start'] not in {x['start'] for x in selected}
                    and score(s['quote'],claim)>0),None)
        if match:selected.append(match)
        if len(selected)>=limit:break
    pages=list(re.finditer(r'<!-- page:(\d+) -->',full))
    source_hash=hashlib.sha256(full.encode()).hexdigest()
    result=[]
    for s in selected:
        e={k:s[k] for k in ('start','end','quote')}
        page=next((int(m[1]) for m in reversed(pages) if m.start()<=s['start']),None)
        if page is not None:e['page']=page
        e.update(scope='full_text_span',source_hash=source_hash,
                 locator=f'论断检索 · 全文字符 {s["start"]+1}–{s["end"]}')
        result.append(e)
    return result


def pdf_matches(path, claims, limit=2):
    """Use geometric text order for numeric claims; retain headers and row labels.

    This is a second view of the page, not a fabricated structured table. Keep
    neighboring pages too: captions, experimental conditions and even sentences
    can continue across a page break. ``limit`` bounds anchor pages; neighbors
    are separate, lower-priority units so small contexts still fit the anchors.
    Failed extraction leaves the exact stored-text excerpts available.
    """
    if path is None or not any(numbers(c) for c in claims):return []
    import pymupdf
    with pymupdf.open(path) as doc:
        if doc.needs_pass:return []
        plain=[page.get_text('text') for page in doc]
        chosen=[]
        for claim in claims:
            wanted=numbers(claim)
            if not wanted:continue
            ranked=sorted(range(len(plain)),key=lambda i:score(plain[i],claim),reverse=True)
            page=next((i for i in ranked if i not in chosen and wanted&numbers(plain[i])),None)
            if page is not None:chosen.append(page)
            if len(chosen)>=limit:break
        if not chosen:return []
        with path.open('rb') as stream:source_hash=hashlib.file_digest(stream,'sha256').hexdigest()
        neighbors=list(dict.fromkeys(j for i in chosen for j in (i+1,i-1)
                                     if 0<=j<len(doc) and j not in chosen))
        return [dict(quote=doc[i].get_text('text',sort=True),page=i+1,scope='pdf_page_layout',
                     source_hash=source_hash,adjacent_context=i not in chosen,
                     locator=f'论断检索 · PDF 第 {i+1} 页（'+
                         ('相邻页上下文；' if i not in chosen else '')+'按版面排列的文本）')
                for i in chosen+neighbors]


def gather(session, entries, draft):
    from app.models import Paper
    from app.config import get_settings
    from app.ingestion.pdf_storage import resolve_pdf
    allowed={p.paper_id for p in entries}
    by_paper={}
    for paragraph in draft.split('\n\n'):
        for pid,claims in cited_claims(paragraph).items():
            if pid in allowed:by_paper.setdefault(pid,[]).extend(claims)
    result=[]
    for pid,claims in by_paper.items():
        paper=session.get(Paper,pid)
        if paper is None or paper.is_deleted:continue
        excerpts=text_matches(paper.full_text or '',claims)
        path=resolve_pdf(paper.pdf_path,get_settings().data_dir/'pdfs')
        try:layout=pdf_matches(path,claims)
        except Exception:layout=[]  # Damaged/missing PDFs do not prevent editing.
        anchors=[e for e in layout if not e.get('adjacent_context')]
        neighbors=[e for e in layout if e.get('adjacent_context')]
        for i,e in enumerate(anchors+excerpts+neighbors):
            result.append(dict(e,paper_id=pid,paper_title=paper.title,ref=f'E{pid}.C{i+1}',
                               purpose='论断相邻页上下文' if e.get('adjacent_context') else '论断对应原文',
                               claim_source=True))
    return result
