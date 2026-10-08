"""Source-version-specific edit proposals; adoption always creates a new file."""
import hashlib
import json
from difflib import SequenceMatcher

from fastapi import HTTPException
from sqlmodel import select

from app.models import Conversation, Message
from app.agent.saved_documents import get_document
from app.agent.document_revisions import public_revision, save_revision


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _proposal(session,message_id,filename,before,after,reason='',start_char=None):
    record=get_document(session,message_id,filename)
    text=record['content']
    if not isinstance(before,str) or not before:
        raise ValueError('请提供原文中的非空片段，保留 Markdown 标记。')
    if not isinstance(after,str) or before==after:
        raise ValueError('替换内容与原文相同，未生成修改建议。')
    if start_char is None:
        positions=[];cursor=0
        while len(positions)<8:
            position=text.find(before,cursor)
            if position<0:break
            positions.append(position);cursor=position+1
        if len(positions)!=1:
            raise ValueError('原片段未唯一定位。请回读文档并提供精确 Markdown；重复位置可指定 start_char。匹配位置：'+str(positions))
        start_char=positions[0]
    if not isinstance(start_char,int) or start_char<0 or text[start_char:start_char+len(before)]!=before:
        raise ValueError('指定位置与原文不一致，请回读对应版本再提供原片段。')
    end=start_char+len(before)
    revised=text[:start_char]+after+text[end:]
    if not revised.strip() or len(revised)>1_000_000:
        raise ValueError('修改后的文档需非空且不超过当前文档容量。')
    version=_digest(text)
    proposal_id=_digest(json.dumps([message_id,filename,version,start_char,before,after],ensure_ascii=False))[:32]
    return record,{'ok':True,'kind':'document_edit_proposal','applied':False,'proposal_id':proposal_id,
        'source_message_id':message_id,'filename':filename,'start_char':start_char,'end_char':end,'source_sha256':version}


def propose_document_edit(session,message_id,filename,before,after,reason='',start_char=None):
    try:
        _,proposal=_proposal(session,message_id,filename,before,after,reason,start_char)
        return json.dumps(proposal,ensure_ascii=False)
    except (LookupError,ValueError) as exc:
        return json.dumps({'error':str(exc)},ensure_ascii=False)


def _latest_descendant(rows, record):
    """Follow saved version links, including manual edits, in this conversation."""
    filenames={record['filename']}
    latest=None
    for row in sorted(rows,key=lambda item:item.id):
        if row.id<=record['message_id']:
            continue
        revision=public_revision(row)
        if revision and revision.get('parent_filename') in filenames:
            filenames.add(revision['filename'])
            latest=(row,revision)
    return latest


def _unchanged_span(original, latest, start, end):
    if original==latest:
        return start,end
    passage=original[start:end]
    if original.count(passage)==1 and latest.count(passage)==1:
        position=latest.index(passage)
        return position,position+len(passage)
    # Rebase the exact original span through unchanged text. Edits elsewhere,
    # including insertions before the target, must survive adopting this edit.
    for kind,a,b,c,d in SequenceMatcher(None,original,latest,autojunk=False).get_opcodes():
        if kind=='equal' and a<=start and end<=b:
            return c+start-a,c+end-a
    raise HTTPException(409,'这一段已在新版本中修改。建议文字已保留，请回读最新版本后调整这一处。')


def apply_document_edit(session,cid,proposal_id,replacement):
    conversation=session.get(Conversation,cid)
    if conversation is None:raise HTTPException(404,'conversation not found')
    rows=session.exec(select(Message).where(Message.conversation_id==cid).order_by(Message.id.desc())).all()
    # A timed-out response can be retried without creating another version.
    for row in rows:
        revision=public_revision(row)
        if revision and revision.get('proposal_id')==proposal_id and revision.get('replacement_sha256')==_digest(replacement):
            return {'message_id':row.id,**revision}
    matched=None
    for row in rows:
        for tool in json.loads(row.agent_state_json or '{}').get('tools',[]):
            if tool.get('name')!='propose_document_edit' or not tool.get('ok'):continue
            try:result=json.loads(tool.get('result',''))
            except (TypeError,ValueError):continue
            if isinstance(result,dict) and result.get('ok') is True and result.get('proposal_id')==proposal_id:
                matched=(row,tool,result);break
        if matched:break
    if not matched:raise HTTPException(404,'当前对话中没有这条修改建议')
    proposal_message,tool,stored=matched
    args=tool.get('args') or {}
    try:
        record,current=_proposal(session,args['message_id'],args['filename'],args['before'],args['after'],
                                 args.get('reason',''),args.get('start_char'))
    except (LookupError,ValueError,KeyError,TypeError) as exc:
        raise HTTPException(409,'原版本已无法定位，请保留修改内容并重新读取文档。') from exc
    if current!=stored:
        raise HTTPException(409,'原版本已发生变化，请保留修改内容并重新生成建议。')
    origin=session.get(Message,record['message_id'])
    target_text=record['content'];target_filename=record['filename']
    descendant=_latest_descendant(rows,record)
    if descendant:
        origin,revision=descendant
        target_text=revision['content'];target_filename=revision['filename']
    start,end=_unchanged_span(record['content'],target_text,current['start_char'],current['end_char'])
    revised=target_text[:start]+replacement+target_text[end:]
    if revised==target_text:
        raise HTTPException(422,'内容与原版本相同，无需另存新版本。')
    if not revised.strip() or len(revised)>1_000_000:
        raise HTTPException(422,'修改后的文档需非空且不超过当前文档容量。')
    sources=json.loads(proposal_message.sources_json or '[]')
    for source in sources:
        if isinstance(source,dict):source['carried_from_message']=proposal_message.id
    note=f"我已采用研究文档《{record['filename']}》的局部修改建议并保存为新版本。后续请使用这份用户采用的修订稿，保留本次局部修改和其他未修改的内容。"
    return save_revision(session,conversation,origin,target_filename,revised,
        extra={'proposal_id':proposal_id,'replacement_sha256':_digest(replacement),'revision_kind':'accepted_suggestion',
               'proposal_source_message_id':record['message_id'],'proposal_source_filename':record['filename']},
        note=note,additional_sources=sources)
