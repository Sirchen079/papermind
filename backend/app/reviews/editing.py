"""Versioned, local paragraph edits. Proposals never overwrite a manuscript."""
import hashlib
import re
from sqlmodel import select
from app.models import Model
from app.models.review import ReviewRevision
from app.providers.selection import pick_llm
from app.providers.purposes import purpose_model
from app.reviews import service, reserves
from app.reviews.context import clip, prepare, segments, text_budget, response_budget
from app.providers.client import EmptyResponseError
from app.reviews.writing import guides, stage_guide
from app.agent.context import estimate_tokens


def blocks(content, version):
    result=[];start=0;offset=0;fence=None
    for line in content.splitlines(keepends=True):
        marker=re.match(r'^\s*(`{3,}|~{3,})',line)
        if marker:
            value=marker[1]
            if fence is None:fence=value
            elif value[0]==fence[0] and len(value)>=len(fence):fence=None
        # Fenced code and display equations remain a single editable block.
        if line.strip()=='$$':fence=None if fence=='$$' else '$$' if fence is None else fence
        if not line.strip() and fence is None:
            if content[start:offset].strip():result.append((start,offset))
            start=offset+len(line)
        offset+=len(line)
    if content[start:].strip():result.append((start,len(content)))
    result=[(a,b-len(content[a:b])+len(content[a:b].rstrip('\r\n'))) for a,b in result]
    return [{'id':hashlib.sha256(f'{version}:{a}:{b}:{content[a:b]}'.encode()).hexdigest()[:24],
             'text':content[a:b],'start':a,'end':b} for a,b in result]


def paragraphs(session, review_id):
    row=service.get(session,review_id)
    return {'version':row.version,'blocks':blocks(row.content,row.version)}


def selected(session,review_id,version,block_id):
    row=service.get(session,review_id)
    if row.version!=version:raise ValueError('正文已有新版本，请刷新后重新选择段落；当前修改可以复制保留。')
    block=next((b for b in blocks(row.content,version) if b['id']==block_id),None)
    if block is None:raise ValueError('选中段落已改变，请重新选择。')
    return row,block


def apply(session,review_id,version,block_id,replacement):
    # One write transaction covers the anchor check and the new revision.
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    row,block=selected(session,review_id,version,block_id)
    if row.status=='running':raise ValueError('请先暂停生成，再应用段落修改。')
    content=replace_blocks(row.content,[(block,replacement)])
    return _save_locked(session,row,content)


def replace_blocks(content,replacements):
    """Apply anchored edits from the end, leaving every other byte untouched."""
    previous=len(content)
    for block,replacement in sorted(replacements,key=lambda item:item[0]['start'],reverse=True):
        a,b=block['start'],block['end']
        if not 0<=a<=b<=previous or content[a:b]!=block['text']:
            raise ValueError('修改位置已改变，请基于当前正文重试。')
        content=content[:a]+replacement+content[b:];previous=a
    return content


def _save_locked(session,row,content):
    from app.models.base import utcnow
    if row.content!=content:
        row.version+=1;row.content=content;row.updated_at=utcnow()
        session.add(ReviewRevision(review_id=row.id,version=row.version,content=content));session.add(row)
    session.commit()
    return service.detail(session,row.id)


def restore(session,review_id,target_version,expected_version):
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    row=service.get(session,review_id)
    if row.status=='running':raise ValueError('请先暂停生成，再恢复版本。')
    if row.version!=expected_version:raise ValueError('正文已有新版本，请刷新后再恢复。')
    old=session.exec(select(ReviewRevision).where(ReviewRevision.review_id==review_id,ReviewRevision.version==target_version)).first()
    if old is None:raise LookupError('历史版本不存在')
    return _save_locked(session,row,old.content)


def propose(session,review_id,version,block_id,instruction):
    row,block=selected(session,review_id,version,block_id)
    choice=purpose_model(session,'review_writing') or pick_llm(session,'chat')
    if choice is None:raise ValueError('配置文本模型后可使用 AI 修改；也可以直接编辑右侧正文。')
    client,provider,model=choice
    config=session.exec(select(Model).where(Model.provider_id==provider.id,Model.model_id==model)).first()
    window=(config.context_window if config else None) or 32768
    effort=config.reasoning_effort if config else None
    original=block['text'];question=row.question
    nearby=row.content[max(0,block['start']-700):block['start']]+row.content[block['end']:block['end']+700]
    entries=service.papers(session,review_id);allowed={p.paper_id for p in entries}
    from app.reviews.evidence import revision_sources, source_text
    from app.reviews.claims import gather
    claim_text=original+'\n\n'+instruction
    evidence=source_text(gather(session,entries,claim_text)+revision_sources(entries,claim_text),window//16)
    from app.reviews.notes import snapshots,context
    cited={int(pid) for pid in re.findall(r'\[P(\d+)\]',claim_text)}
    note_context=context([n for p in entries if p.paper_id in cited
                          for n in snapshots(session,p.paper_id)],window//16)
    reserve_key=reserves.model_key(provider,model,window,effort)
    reasoning_budget=reserves.load(session,review_id).get(reserve_key)
    engine=session.get_bind()
    session.rollback()  # Do not hold a read transaction across local inference.
    guide=stage_guide(guides()[0],'edit',window//6)
    results=[];warnings=[]
    # A large input window does not imply a similarly large output allowance.
    # Bound edits by the actual passage, including on million-token models.
    for part in segments(original,max(128,min(1800,window//8))):
        prompt=('仅修改选中的正文片段，完成用户的修改要求。保持未要求改变的事实、术语与引用，'
                '新判断需有提供的证据；需要补充的事实局部标注。不要改写其他段落，不添加说明或外围代码围栏。'
                '\n修改要求：'+instruction)
        material={'选中正文':part,'相邻正文（仅供衔接）':clip(nearby,window//32),'原文依据':clip(evidence,window//16)}
        if note_context:material['当前研究笔记（与论文原文分开）']=note_context
        requested=min(4096,max(600,estimate_tokens(part)*2+200))
        def increase_reserve(cap):
            value=max(4096,cap*2-text_budget(window,requested))
            if response_budget(window,requested,effort,value)<=cap:return None
            return reserves.increase(engine,review_id,reserve_key,value)
        partial=None
        for attempt in range(2):
            options=dict(reasoning_effort=effort,reasoning_budget=reasoning_budget,required_text=part)
            messages,output,_=prepare(service.SYSTEM,clip(question,window//24),prompt,material,window,requested,guide['text'],**options)
            # Keep the selected text intact, reducing background first.
            if part not in messages[-1]['content']:
                messages,output,_=prepare(service.SYSTEM,'',prompt,part,window,requested,'',**options)
            if part not in messages[-1]['content']:
                if partial is not None:result=partial;break
                raise ValueError('当前上下文无法同时容纳修改要求和选中正文，请缩短修改要求或增大模型上下文；原文保留。')
            try:
                result=client.complete(provider,model,messages,request_kind='library_review',ref_id=review_id,max_tokens=output,reasoning_effort='low')
                if not service.tolerant_text(result.content):
                    raise EmptyResponseError('模型未返回修改正文',output_exhausted=getattr(result,'output_exhausted',False) is True)
                if getattr(result,'output_incomplete',False) is True:
                    if partial is None or len(result.content)>len(partial.content):partial=result
                    if getattr(result,'output_exhausted',False) is True:
                        increased=increase_reserve(output)
                        if increased is not None:
                            reasoning_budget=increased
                            if not attempt:continue
                    result=partial
                break
            except EmptyResponseError as exc:
                increased=increase_reserve(output) if exc.output_exhausted else None
                if increased is not None:reasoning_budget=increased
                if partial is not None:result=partial;break
                if attempt or increased is None:raise
            except Exception:
                if partial is None:raise
                result=partial;break
        text=service.tolerant_text(result.content)
        if not text:raise ValueError('模型未返回修改正文，原文仍保留，可重试或直接编辑。')
        text,warning=service.clean_citations(text,allowed);results.append(text)
        if warning:warnings.append(warning)
        if getattr(result,'output_incomplete',False) is True:
            warnings.append('模型报告正文未完整返回，已保留收到的修改稿；可继续编辑或重新请求，原文尚未改变。')
    return {'base_version':version,'block_id':block_id,'original':original,'replacement':'\n\n'.join(results),
            'warning':'；'.join(warnings),'skill':{k:v for k,v in guide.items() if k!='text'}}
