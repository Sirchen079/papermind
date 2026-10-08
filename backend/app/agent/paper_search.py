"""Expose the local passage index to the agent's research loop."""
import json
import logging
import re
from app.models import Paper
from app.rag import scalable
from app.rag.passages import with_context


def search_paper_text(session, query, paper_ids=None, top_k=6):
    query=(query or '').strip()
    if not query or paper_ids==[]:return '[]'
    limit=max(1,min(int(top_k),12))
    ids=list(dict.fromkeys(paper_ids)) if paper_ids is not None else None
    mode='hybrid'
    try:
        hits=scalable.hybrid(session,query,ids,limit)
    except Exception:
        # A provider outage need not prevent reading locally indexed text.
        logging.getLogger(__name__).warning('Passage search using local keyword results')
        hits=[chunk for chunk,_ in scalable.lexical(session,query,ids,limit)]
        mode='keyword_fallback'
    if not hits:
        return json.dumps([{'note':'当前索引没有命中。未建立索引的论文也可用 get_paper_full_text 直接阅读；没有命中不代表原文没有相关内容。'}],ensure_ascii=False)
    rows=[]
    for chunk in with_context(session,hits):
        paper=session.get(Paper,chunk.paper_id)
        if paper is None or paper.is_deleted or (ids is not None and paper.id not in ids):continue
        anchor=getattr(chunk,'anchor_text',chunk.text)
        match=re.match(r'^\[第 (\d+) 页\]',anchor)
        segments=getattr(chunk,'context_segments',[])
        pages=list(dict.fromkeys(([int(match[1])] if match else [])+[s['page'] for s in segments if s.get('page')]))
        kind='metadata' if chunk.ordinal==0 and not match else 'full_text'
        rows.append({'paper_id':paper.id,'title':paper.title,'text':chunk.text,
            'type':kind,'retrieval_mode':mode,'chunk_ordinal':chunk.ordinal,'pages':pages,
            'locator':('PDF 第 '+ '、'.join(map(str,pages))+' 页') if pages else
                '标题与摘要' if kind=='metadata' else f'正文片段 {chunk.ordinal}'})
    return json.dumps(rows,ensure_ascii=False)
