"""Update an existing manuscript through the editor's anchored paragraphs."""
import json
import re
from sqlmodel import Session
from app.agent.context import estimate_tokens
from app.agent.evidence_review import parse_review_response
from app.reviews.context import balanced,segments
from app.reviews.editing import blocks,replace_blocks
from app.reviews.service import digest,get,clean_citations

PATCH = ('依据 Nature 局部修订流程，更新当前版本的综述正文。'
         '本次只更新给出的正文片段；保持研究者的纠正、术语及已有结构。'
         '根据新增或改变材料补充必要结果、修正受影响判断，并处理直接相关的前后矛盾。'
         '仅配置变化时核对现有论断，不为换模型重写整篇。分析简报不是独立证据，事实以原文为准。'
         '仅返回需要修改的段落，不复述未改段落，不重新生成提纲或整篇。'
         '返回 JSON {"edits":[{"block_id":"给定id","op":"replace","replacement":"该段完整修改正文","reason":"具体修改原因"}]}。'
         '需要新增内容时用 op="append" 将 replacement 接在指定段落之后；可加入确有必要的新标题。'
         '无必要修改时返回 {"edits":[]}。只使用目标段落的 id，保留 [P编号]，不添加审批步骤。')


def units(content,version,budget):
    result=[]
    for block in blocks(content,version):
        parts=segments(block['text'],budget);offset=block['start']
        for i,part in enumerate(parts):
            result.append(dict(id=block['id'] if len(parts)==1 else f'{block["id"]}:{i}',
                               text=part,start=offset,end=offset+len(part)))
            offset+=len(part)
    return result


def batches(items,budget):
    batch=[];cost=0
    for item in items:
        size=estimate_tokens(json.dumps({'id':item['id'],'text':item['text']},ensure_ascii=False))+8
        if batch and cost+size>budget:
            yield batch;batch=[];cost=0
        batch.append(item);cost+=size
    if batch:yield batch


def edits(raw,targets,allowed):
    parsed=parse_review_response(raw)
    if not isinstance(parsed,dict) or not isinstance(parsed.get('edits'),list):
        raise ValueError('未返回段落修改列表，建议已保存，原文保留。')
    by_id={b['id']:b for b in targets};seen=set();accepted=[];warnings=[];reasons=[]
    for item in parsed['edits']:
        if not isinstance(item,dict):warnings.append('一项建议缺少段落位置，未应用。');continue
        bid=item.get('block_id');replacement=item.get('replacement',item.get('after'))
        op=item.get('op','replace')
        if not isinstance(bid,str) or bid not in by_id or bid in seen or not isinstance(replacement,str) or op not in {'replace','append'}:
            warnings.append('一项建议的位置或修改内容不可用，其他有效修改继续应用。');continue
        seen.add(bid);block=by_id[bid]
        replacement,note=clean_citations(replacement,allowed)
        if note:warnings.append(note)
        if op=='append':replacement=block['text']+'\n\n'+replacement
        if replacement!=block['text']:
            accepted.append((block,replacement))
            reason=item.get('reason')
            reasons.append(reason if isinstance(reason,str) and reason.strip() else '依据当前材料更新相关段落。')
    return accepted,warnings,reasons


def update(engine,review_id,body,entries,delta,window,question,signature,nature,researcher,
           ask,stage,save_section,cached_section,active):
    from app.reviews.evidence import revision_sources,source_text
    from app.reviews.claims import gather
    from app.reviews.synthesis import summarize
    with Session(engine) as s:version=get(s,review_id).version
    changed='\n\n'.join(f'[P{p.paper_id}] {p.title}（{p.status}）\n{p.analysis}\n{p.warning}' for p in delta)
    delta_budget=max(256,min(6000,window//8))
    if estimate_tokens(changed)>delta_budget:
        changed=summarize(delta,max(600,min(24000,window//2)),question,signature,researcher,
                          ask,stage,save_section,cached_section,active)
        if changed is None:return body,[],{'changes':[],'evidence':[]}
    context=balanced(body,max(128,min(2400,window//12)))
    target_budget=max(128,min(6000,window//10))
    groups=list(batches(units(body,version,max(128,target_budget-100)),target_budget))
    changes=[];warnings=[];notes=[];raw_suggestions=[];saved_evidence=[]
    for i,group in enumerate(groups):
        if not active():return body,warnings,{'changes':[],'evidence':[]}
        stage(f'Nature Writing：局部更新 {i+1}/{len(groups)}')
        target=json.dumps([{'id':b['id'],'text':b['text']} for b in group],ensure_ascii=False)
        claims='\n\n'.join(b['text'] for b in group)
        with Session(engine) as s:evidence=gather(s,entries,claims)+revision_sources(entries,claims)
        # Keep a separate share for the new paper. Appending it behind dozens
        # of existing citations lets source_text spend its entire budget first.
        new_evidence=revision_sources(delta,' '.join(f'[P{p.paper_id}]' for p in delta)) if delta else []
        source_budget=max(256,min(8000,window//6))
        new_budget=source_budget//2 if new_evidence else 0
        material={'目标段落':target,'当前版本的综述正文（前后文）':context,
                  '新增或改变的论文分析':balanced(changed,delta_budget) if changed else '材料未变，本次沿当前稿核对，保留无需改变的内容。',
                  '原文依据':source_text(evidence,source_budget-new_budget)}
        if new_evidence:material['新增或改变论文的原文']=source_text(new_evidence,new_budget)
        evidence+=new_evidence
        from app.reviews.notes import from_entries,add_context
        # Changed notes must reach the patch writer even if its brief omitted
        # the correction, or the current paragraph does not yet cite that paper.
        cited={int(pid) for pid in re.findall(r'\[P(\d+)\]',claims)}
        relevant=list(delta)+[p for p in entries if p not in delta and p.paper_id in cited]
        note_sources=from_entries(relevant)
        add_context(material,note_sources,max(256,min(4000,window//12)))
        evidence+=note_sources
        fp=digest([body,material,signature,PATCH,'paragraph-update-v1'])
        ordinal=-300000-i;cached=cached_section(ordinal,fp)
        if cached:raw=cached.content;warning=''
        else:
            raw,warning=ask(PATCH,material,max(1200,min(6000,estimate_tokens(target))),
                            guide=nature,phase='update',required_text=target,structured=True)
        try:
            accepted,issues,reasons=edits(raw,group,{p.paper_id for p in entries})
            changes.extend(accepted);notes.extend(reasons);warnings.extend(issues)
            if accepted:saved_evidence.extend(evidence)
            if issues:raw_suggestions.append(raw)
        except (ValueError,TypeError) as exc:
            issues=[str(exc)];warnings.extend(issues)
            raw_suggestions.append(raw or '本组模型未返回修改建议。')
        if warning:warnings.append(warning)
        if not cached:save_section(ordinal,'局部修改建议',fp,raw,evidence,warning='；'.join([warning,*issues]).strip('；'))
    result=replace_blocks(body,changes)
    report=f'本次更新 {len(changes)} 处，其他正文保持原样。'
    if notes:report+='\n\n'+'\n'.join('- '+n for n in notes)
    if warnings:report+='\n\n需继续处理：\n'+'\n'.join('- '+n for n in dict.fromkeys(warnings))
    if raw_suggestions:report+='\n\n未应用的模型建议（保留供继续编辑）：\n\n'+'\n\n'.join(raw_suggestions)
    save_section(-99998,'本次局部更新',digest([body,signature,PATCH]),report)
    records=[];shift=0
    for (block,replacement),reason in sorted(zip(changes,notes),key=lambda pair:pair[0][0]['start']):
        records.append({'before':block['text'],'after':replacement,'reason':reason,'after_start':block['start']+shift})
        shift+=len(replacement)-len(block['text'])
    return result,warnings,{'changes':records,'evidence':saved_evidence}
