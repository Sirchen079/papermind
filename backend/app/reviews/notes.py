"""Carry saved reading work into reviews without calling it paper evidence."""
import hashlib
import json
from sqlmodel import select
from app.models.reading import PaperNote

SCOPE = 'researcher_note'
GUIDANCE = ('以下是本地研究笔记，可能包含人工或 AI 分析、纠正和待测设想，不是论文原文，'
            '保存不代表研究者已采用。结合原文保留已记录的条件；有分歧时说明具体分歧，'
            '不要把笔记中的推测写成论文已报告的结果。')


def snapshots(session, paper_id):
    return [dict(ref=f'N{n.id}.v{n.version}', paper_id=paper_id, scope=SCOPE,
                 note_id=n.id, version=n.version, kind=n.kind, tags=json.loads(n.tags_json),
                 quote=n.content, source_hash=hashlib.sha256(n.content.encode()).hexdigest(),
                 locator=f'研究笔记 #{n.id} · v{n.version}（研究记录，非论文原文）',
                 purpose='研究笔记')
            for n in session.exec(select(PaperNote).where(PaperNote.paper_id==paper_id)
                                  .order_by(PaperNote.id)) if n.content.strip()]


def from_entries(entries):
    return [dict(e, paper_id=p.paper_id) for p in entries
            for e in json.loads(p.evidence_json) if e.get('scope')==SCOPE]


def context(sources, tokens=None):
    from app.reviews.context import balanced
    text='\n\n'.join(f'[P{n["paper_id"]}] {n["locator"]}\n{n["quote"]}' for n in sources)
    if not text:return ''
    fitted=balanced(text,tokens) if tokens is not None else text
    return GUIDANCE+'\n\n'+fitted+('\n〔笔记内容因上下文容量有所节选，完整快照可回查。〕' if fitted!=text else '')


def add_context(material, sources, tokens):
    text=context(sources,tokens)
    if text:material['研究笔记（与论文原文分开）']=text
    return material
