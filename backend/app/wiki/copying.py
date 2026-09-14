"""Explicit cross-project copies retain evidence but have no foreign live IDs."""
import json
import re
from uuid import uuid4
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import WikiPage, WikiCopy
from app.workspaces.context import bind_workspace
from app.wiki.evidence import digest
from app.wiki.service import Conflict, lock, page, revision, used_evidence, _append


def detach(evidence, origin):
    refs = {}
    def collect(items):
        for item in items:
            if item.get('ref'):
                refs[item['ref']] = 'W' + digest([origin.id, item['ref'], item.get('dependency')])[:24]
            collect(item.get('underlying_evidence', []))
    collect(evidence)
    def rewrite(text):
        return re.sub(r'\[([^\]\n]+)\]', lambda m: '['+refs.get(m[1],m[1])+']', text)
    def visit(item):
        result = {k:v for k,v in item.items() if k not in ('dependency','paper_id','underlying_evidence','ref','underlying_refs')}
        result['captured_from'] = {'workspace':origin.id,'name':origin.name,'ref':item.get('ref'),
                                   'dependency':item.get('dependency'),'paper_id':item.get('paper_id'),
                                   'earlier':item.get('captured_from')}
        if item.get('ref'):
            result['ref'] = refs[item['ref']]
        result['quote'] = rewrite(item.get('quote',''))
        if item.get('underlying_refs'):
            result['underlying_refs'] = [refs.get(ref,ref) for ref in item['underlying_refs']]
        if item.get('underlying_evidence'):
            result['underlying_evidence'] = [visit(child) for child in item['underlying_evidence']]
        return result
    return [visit(item) for item in evidence], refs, rewrite


def copy_topic(registry, origin, target_id, page_id, number, request_id):
    if origin.id == target_id:
        raise Conflict('请选择另一个研究项目。')
    target = registry.get(target_id)
    if target['archived']:
        raise Conflict('目标项目已归档，请先恢复。')
    reason = registry.unavailable_reason(target_id)
    if reason:
        raise Conflict(reason)
    destination = registry.context(target_id)
    with bind_workspace(destination):
        engine = get_engine()
    with Session(engine) as dest:
        lock(dest)
        receipt = dest.get(WikiCopy, request_id)
        if receipt:
            if (receipt.source_workspace,receipt.source_page_id,receipt.source_revision) != (origin.id,page_id,number):
                raise Conflict('同一个复制请求对应不同专题版本。')
            return {**receipt.model_dump(mode='json'),'reused':True}
        with bind_workspace(origin), Session(get_engine()) as source:
            source.connection().exec_driver_sql('BEGIN')
            original = page(source,page_id)
            chosen = revision(source,page_id,number)
            if chosen is None:
                raise LookupError('原专题版本不存在。')
            evidence, refs, rewrite = detach(used_evidence(chosen), origin)
            copied = WikiPage(id=str(uuid4()),title=original.title)
            dest.add(copied);dest.flush()
            support={'pending':'待核对','supported':'已核对支持关系','partial':'部分支持','unsupported':'来源不支持','unclear':'仍不明确'}.get(chosen.support_status,chosen.support_status)
            note=f'从“{origin.name}”复制专题 v{number}。原核对状态：{support}。'
            if chosen.review_note:
                note+='原核对备注：'+chosen.review_note
            _append(dest,copied,request_id,digest([origin.id,page_id,number]),rewrite(chosen.content),
                    evidence,[refs[ref] for ref in json.loads(chosen.references_json)],origin='copied',
                    change=note)
            receipt = WikiCopy(request_id=request_id,source_workspace=origin.id,source_name=origin.name,
                               source_page_id=page_id,source_revision=number,source_title=original.title,page_id=copied.id)
            dest.add(receipt);dest.commit();dest.refresh(receipt)
            return {**receipt.model_dump(mode='json'),'reused':False}
