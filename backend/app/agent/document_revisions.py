"""Local document snapshots and revisions preserve their content's authorship."""
import json
from fastapi import HTTPException
from sqlmodel import select
from app.models import Conversation, Message
from app.models.base import utcnow
from app.agent.research_actions import save_document


def public_revision(message):
    metadata=json.loads(message.request_json or '{}').get('document_revision')
    if message.role!='user' or not isinstance(metadata,dict):
        return None
    return {**metadata,'content':message.model_context or ''}


def saved_answer_notice(message, revision):
    """The answer is already in history; keep the durable reread pointer."""
    return (message.content + '\n这是 AI 原回答的保存记录。需要回读正文或来源时，使用 read_saved_document：'
            f'message_id={message.id}; filename={revision["filename"]}')


def revision_context(message, revision):
    """Serialize a durable version's identity separately from its editable notice.

    A custom notice may omit the filename or describe an unadopted audit. Keep
    that wording and the exact body; neither infer adoption nor switch branches.
    """
    if revision.get('revision_kind') == 'saved_answer':
        return saved_answer_notice(message, revision)
    metadata = {key: revision[key] for key in (
        'parent_message_id', 'parent_filename', 'root_filename', 'revision_kind',
        'audit_author', 'adoption_status') if key in revision}
    return (
        f'[已保存文档版本] message_id={message.id}; filename={revision["filename"]}\n'
        + '版本记录：' + json.dumps(metadata, ensure_ascii=False) + '\n'
        + '可用 read_saved_document 按以上编号和文件名回读此版本及来源；父版本用于追溯，'
          '不替代此版本。保存不等于研究者采用，采用状态以记录和用户说明为准。\n'
        + '继续或压缩此稿时保留其既定条件、纠正和未决事项；新建议另行说明，'
          '不要把既定条件改写成待决定事项。用户另行指定版本或研究方向时按当前要求处理。\n\n'
        + message.content + '\n\n[此版本正文]\n' + revision['content']
    )


def latest_turn(session,cid):
    return next((message for message in session.exec(select(Message).where(Message.conversation_id==cid)
        .order_by(Message.id.desc())) if public_revision(message) is None),None)


def resume_with_revisions(session,cid,after_id,state):
    from app.agent.attachments import text_content
    seen=set(state.get('manual_revision_ids',[]))
    messages=list(state['messages'])
    for row in session.exec(select(Message).where(Message.conversation_id==cid,Message.id>after_id).order_by(Message.id)):
        revision = public_revision(row)
        if revision and row.id not in seen:
            captured = revision.get('revision_kind') == 'saved_answer'
            if not any(m.get('role')=='user' and row.content in text_content(m.get('content'))
                       and (captured or (row.model_context or '') in text_content(m.get('content'))) for m in messages):
                content = revision_context(row, revision)
                messages.append({'role':'user','content':content})
            seen.add(row.id)
    return {**state,'messages':messages,'manual_revision_ids':sorted(seen)}


def _owns_document(message, filename):
    revision=public_revision(message)
    if revision and revision.get('filename')==filename:
        return True
    for tool in json.loads(message.agent_state_json or '{}').get('tools',[]):
        if tool.get('name')!='save_document' or not tool.get('ok'):
            continue
        try:result=json.loads(tool.get('result',''))
        except (TypeError,ValueError):continue
        if isinstance(result,dict) and result.get('ok') is True and result.get('filename')==filename:
            return True
    return False


def capture_answer(session, cid, message_id):
    """Save an existing answer verbatim, without synthesizing an AI tool call."""
    conversation = session.get(Conversation, cid)
    origin = session.get(Message, message_id)
    if conversation is None or origin is None or origin.conversation_id != cid:
        raise HTTPException(404, '当前对话中没有这条回答')
    if origin.role != 'assistant' or not origin.content.strip():
        raise HTTPException(422, '这条消息没有可保存的回答正文')
    # Retrying a lost HTTP response must return the same snapshot, even after
    # later edits. Its revision descendants remain discoverable as usual.
    for row in session.exec(select(Message).where(Message.conversation_id == cid,
            Message.id > message_id, Message.request_json.contains('saved_answer')).order_by(Message.id)):
        saved = public_revision(row)
        if saved and saved.get('revision_kind') == 'saved_answer' and saved.get('source_message_id') == message_id:
            return {'message_id': row.id, **saved}
    try:
        result = json.loads(save_document(session, f'研究回答-{message_id}.md', origin.content))
    except OSError as exc:
        raise HTTPException(500, '文档保存失败，原回答仍保留，可重试保存。') from exc
    metadata = {key: result[key] for key in ('filename', 'download_url')}
    metadata.update(revision_kind='saved_answer', source_message_id=message_id,
                    root_filename=result['filename'], parent_filename=None,
                    source_model=origin.model, source_delivery_status=origin.delivery_status)
    note = f"已将 AI 回答原样保存为文档《{result['filename']}》，可继续编辑与引用。"
    sources = json.loads(origin.sources_json or '[]')
    for source in sources:
        if isinstance(source, dict):
            source['carried_from_message'] = origin.id
    row = Message(conversation_id=cid, role='user', content=note, model_context=origin.content,
                  request_json=json.dumps({'content': note, 'document_revision': metadata}, ensure_ascii=False),
                  sources_json=json.dumps(sources, ensure_ascii=False), delivery_status='complete')
    session.add(row); conversation.updated_at = utcnow(); session.add(conversation)
    session.commit(); session.refresh(row)
    return {'message_id': row.id, **metadata, 'content': origin.content}


def revise_document(session,cid,filename,content):
    conversation=session.get(Conversation,cid)
    if conversation is None:
        raise HTTPException(404,'conversation not found')
    if not content.strip():
        raise HTTPException(422,'文档内容不能为空')
    messages=session.exec(select(Message).where(Message.conversation_id==cid).order_by(Message.id.desc())).all()
    origin=next((message for message in messages if _owns_document(message,filename)),None)
    if origin is None:
        raise HTTPException(404,'当前对话中没有这份已保存文档')
    if messages:
        last=public_revision(messages[0])
        if last and last.get('parent_filename')==filename and last['content']==content:
            return {'message_id':messages[0].id,**last}
    return save_revision(session,conversation,origin,filename,content)


def save_revision(session,conversation,origin,filename,content,*,extra=None,note=None,additional_sources=None):
    """Save a user-adopted version, retaining the exact source version's evidence."""
    previous=public_revision(origin) or {}
    root_filename=previous.get('root_filename') or previous.get('parent_filename') or filename
    try:
        result=json.loads(save_document(session,root_filename,content))
    except OSError as exc:
        raise HTTPException(500,'保存修订版失败，请检查磁盘空间或文件权限；编辑内容仍可重试保存。') from exc
    metadata={key:result[key] for key in ('filename','download_url')}
    metadata['parent_filename']=filename
    metadata['parent_message_id']=origin.id
    metadata['root_filename']=root_filename
    metadata.update(extra or {})
    note=note or f"我已手动修订研究文档《{filename}》，保存为《{result['filename']}》。后续请以这份用户修订稿为准，保留我更正的事实与条件。"
    sources=json.loads(origin.sources_json or '[]')
    for source in sources:
        if isinstance(source,dict) and (source.get('paper_id') or source.get('source_type') == 'web'):
            source['carried_from_message']=origin.id
    if additional_sources:
        from app.agent.provenance import merge_sources
        merge_sources(sources,additional_sources)
    row=Message(conversation_id=conversation.id,role='user',content=note,model_context=content,
        request_json=json.dumps({'content':note,'document_revision':metadata},ensure_ascii=False),
        sources_json=json.dumps(sources,ensure_ascii=False),delivery_status='complete')
    session.add(row);conversation.updated_at=utcnow();session.add(conversation);session.commit();session.refresh(row)
    return {'message_id':row.id,**metadata,'content':content}
