import hashlib
import re
from sqlmodel import Session, select
from app.models import Paper, PaperExcerpt


def terms(text: str) -> set[str]:
    tokens = set(re.findall(r'[a-z0-9_]{2,}', text.lower()))
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        tokens.update(run[i:i+2] for i in range(len(run)-1))
    return tokens


def collect_materials(session: Session, paper_ids: list[int], question: str) -> list[dict]:
    """Select bounded spans across the whole extracted text, never invent pages."""
    result = []
    query = terms(question) | {'dataset','evaluation','experiment','split','baseline','limitation','appendix'}
    for paper_id in paper_ids:
        paper = session.get(Paper, paper_id)
        if paper is None or paper.is_deleted:
            raise LookupError(f'论文 {paper_id} 不存在或已删除')
        full = paper.full_text or ''
        abstract = paper.abstract or ''
        excerpts = session.exec(select(PaperExcerpt).where(PaperExcerpt.paper_id == paper_id).order_by(PaperExcerpt.id)).all()
        fingerprint = hashlib.sha256((full+'\0'+abstract+'\0'+str([(e.id,e.quote,e.page,e.section) for e in excerpts])).encode()).hexdigest()
        evidence = []
        def add(quote, scope, locator, **extra):
            if quote.strip():
                evidence.append(dict(ref=f'E{paper_id}.{len(evidence)+1}',paper_id=paper_id,quote=quote,scope=scope,locator=locator,source_hash=fingerprint,**extra))
        if abstract:
            add(abstract[:2400], 'abstract', '摘要（最多 2400 字符）')
        for excerpt in excerpts[:4]:
            # A saved excerpt is a researcher's record, not a validated PDF extraction.
            add(excerpt.quote[:1800], 'excerpt', f'摘录 #{excerpt.id}'+(f' · 第 {excerpt.page} 页' if excerpt.page else ''), page=excerpt.page, section=excerpt.section)
        spans = [(start,full[start:start+1800]) for start in range(0,len(full),1800)]
        ranked = sorted(spans,key=lambda item:(-len(query & terms(item[1])), item[0]))[:6]
        for start,text in sorted(ranked):
            add(text, 'full_text_span', f'抽取全文字符 {start+1}–{start+len(text)}（非页码）', start=start, end=start+len(text))
        result.append(dict(paper_id=paper_id,title=paper.title or f'论文 {paper_id}',source_hash=fingerprint,coverage='selected_full_text_spans' if full else ('abstract_and_excerpts' if evidence else 'no_text'),total_characters=len(full),evidence=evidence))
    return result
