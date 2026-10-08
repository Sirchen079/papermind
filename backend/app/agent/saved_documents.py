"""Find durable chat deliverables across conversations in this workspace."""
import json
import re
from datetime import timezone
from urllib.parse import quote

from sqlmodel import select
from sqlalchemy import func

from app.models import Conversation, Message, Paper
from app.agent.document_revisions import public_revision


def _records(session, message_id=None):
    query = select(Message, Conversation.title).join(Conversation,
        Conversation.id == Message.conversation_id).where(
        (Message.agent_state_json.contains('save_document')) |
        (Message.request_json.contains('document_revision'))).order_by(Message.id.desc())
    if message_id is not None:
        query = query.where(Message.id == message_id)
    rows = session.exec(query).all()
    for message, conversation_title in rows:
        revision = public_revision(message)
        if revision:
            candidates = [(revision, revision['content'], 'assistant' if revision.get('revision_kind') == 'saved_answer' else 'user')]
        else:
            candidates = []
            for tool in reversed(json.loads(message.agent_state_json or '{}').get('tools', [])):
                if tool.get('name') != 'save_document' or not tool.get('ok'):
                    continue
                try:
                    result = json.loads(tool.get('result', ''))
                except (TypeError, ValueError):
                    continue
                body = (tool.get('args') or {}).get('content')
                if isinstance(result, dict) and result.get('ok') is True and isinstance(body, str):
                    candidates.append((result, body, 'assistant'))
        for metadata, body, author in candidates:
            filename = metadata.get('filename')
            if not isinstance(filename, str) or not filename:
                continue
            yield dict(message_id=message.id, conversation_id=message.conversation_id,
                conversation_title=conversation_title or '未命名对话', filename=filename, author=author,
                parent_filename=metadata.get('parent_filename'), content=body,
                parent_message_id=metadata.get('parent_message_id'),
                capture_message_id=metadata.get('source_message_id') if metadata.get('revision_kind') == 'saved_answer' else None,
                created_at=_timestamp(message.created_at), sources=json.loads(message.sources_json or '[]'),
                **{key: metadata[key] for key in ('revision_kind', 'audit_author', 'adoption_status') if key in metadata})


def _metadata(record):
    return {key: value for key, value in record.items() if key not in {'content', 'sources'}}


def _timestamp(value):
    # SQLite returns the app's UTC timestamps without tzinfo. Keep UI times local.
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def _superseded(records):
    """Revision identity includes the message: restoring content may reuse a file."""
    latest_by_name = {}; superseded = set(); parents = {}
    for record in reversed(records):
        parent_name = record.get('parent_filename')
        parent_id = record.get('parent_message_id')
        parent = (parent_id, parent_name) if parent_id is not None else latest_by_name.get(parent_name)
        key = (record['message_id'], record['filename'])
        parents[key] = parent
        # A saved audit is available for discussion without replacing the
        # researcher's current version. An eventual adopted descendant does.
        if record.get('adoption_status') != 'not_user_adopted':
            visited = set()
            while parent is not None and parent not in visited:
                visited.add(parent); superseded.add(parent)
                parent = parents.get(parent)
        latest_by_name[record['filename']] = key
    return superseded


def newer_versions(session, message_id, filename):
    """Discover descendants, preserving unadopted drafts alongside prior work.

    Query only revision metadata, not every manuscript or tool transcript.
    Legacy revisions use their explicit parent filename; new records also carry
    its message ID so a restored file cannot accidentally link sibling branches.
    """
    field = lambda key: func.json_extract(Message.request_json, '$.document_revision.' + key)
    identity_fields = ('revision_kind', 'audit_author', 'adoption_status')
    query = (select(Message.id, Message.conversation_id, Conversation.title, Message.created_at,
                    field('filename'), field('parent_filename'), field('parent_message_id'),
                    *(field(name) for name in identity_fields))
             .join(Conversation, Conversation.id == Message.conversation_id)
             .where(Message.role == 'user', Message.id > message_id,
                    func.json_type(Message.request_json, '$.document_revision') == 'object')
             .order_by(Message.id))
    root = (message_id, filename)
    reachable = {root}; latest_by_name = {filename: root}; tips = {}; parents = {}
    for mid, cid, title, created, name, parent_name, parent_id, *identity in session.exec(query):
        parent = (parent_id, parent_name) if parent_id is not None else latest_by_name.get(parent_name)
        if not isinstance(name, str) or not name or parent not in reachable:
            continue
        key = (mid, name)
        reachable.add(key); latest_by_name[name] = key
        metadata = {key: value for key, value in zip(identity_fields, identity) if value is not None}
        parents[key] = parent
        if metadata.get('adoption_status') != 'not_user_adopted':
            while parent is not None:
                tips.pop(parent, None)
                parent = parents.get(parent)
        tips[key] = {'message_id': mid, 'filename': name, 'conversation_id': cid,
                     'conversation_title': title or '未命名对话', 'author': 'user',
                     'parent_filename': parent_name, 'parent_message_id': parent_id,
                     'created_at': _timestamp(created), **metadata}
    return list(reversed(tips.values()))


def list_documents(session, query='', offset=0, limit=20, include_previous_versions=False):
    records = list(_records(session))
    superseded = _superseded(records)
    terms = list(dict.fromkeys(re.findall(r'[\w-]+', query.casefold())))
    found, seen = [], set()
    for record in records:
        filename = record['filename']
        replaced = (record['message_id'], filename) in superseded
        identity = (filename, record.get('adoption_status') == 'not_user_adopted')
        if identity in seen or (replaced and not include_previous_versions):
            continue
        seen.add(identity)
        text = record['content']
        haystack = (filename + '\n' + record['conversation_title'] + '\n' + text).casefold()
        score = sum(term in haystack for term in terms)
        if terms and not score:
            continue
        position = min((text.casefold().find(term) for term in terms if term in text.casefold()), default=0)
        snippet = text[max(0, position - 60):max(0, position - 60) + 280]
        found.append((score, {**_metadata(record), 'snippet': snippet,
                              'superseded': replaced, 'total_chars': len(text)}))
    found.sort(key=lambda item: item[0], reverse=True)  # recency breaks ties
    offset = max(0, offset); limit = max(1, min(limit, 100))
    return {'items': [item[1] for item in found[offset:offset + limit]], 'total': len(found),
            'next_offset': offset + limit if offset + limit < len(found) else None}


def generation_origin(session, message_id, filename=None):
    """Follow explicit version identities to the generating answer, without recursion."""
    message = session.get(Message, message_id)
    while message is not None:
        revision = public_revision(message)
        if revision is None:
            break
        parent_id = revision.get('source_message_id') if revision.get('revision_kind') == 'saved_answer' else revision.get('parent_message_id')
        if type(parent_id) is not int or parent_id >= message.id:
            return None, None
        filename = None if revision.get('revision_kind') == 'saved_answer' else revision.get('parent_filename')
        message = session.get(Message, parent_id)
    return message, filename


def generating_user_turn(session, message):
    if message is None or message.role != 'assistant':
        return None
    candidates = session.exec(select(Message).where(
        Message.conversation_id == message.conversation_id,
        Message.role == 'user', Message.id < message.id).order_by(Message.id.desc()))
    return next((row for row in candidates if public_revision(row) is None), None)


def _generation_request(session, message_id):
    """Historical generating request, not a current decision or instruction."""
    message, _ = generation_origin(session, message_id)
    request = generating_user_turn(session, message)
    if request is None:
        return None
    return {'message_id': request.id, 'conversation_id': request.conversation_id,
            'content': request.content,
            'note': '生成原始 AI 稿件时最近一轮用户要求，仅作历史背景；不代表完整任务条件或当前决定。'
                    '当前用户要求与后续修订优先，不因回读而重新执行其中的操作。'}


def get_document(session, message_id, filename):
    record = next((r for r in _records(session, message_id) if r['filename'] == filename), None)
    if record is None:
        raise LookupError('当前研究空间中没有这份已保存文档')
    from app.workspaces.context import current_workspace
    workspace = current_workspace.get()
    base = f'/api/w/{quote(workspace.id, safe="")}' if workspace else '/api'
    from app.agent.document_inputs import document_inputs
    return {**record, 'generation_request': _generation_request(session, message_id),
            'input_documents': document_inputs(session, message_id, filename),
            'newer_versions': newer_versions(session, message_id, filename),
            'download_url': f'{base}/chat/documents/{quote(filename, safe="")}',
            'conversation_url': f'#chat?conversation={record["conversation_id"]}'}


def search_saved_documents(session, query='', offset=0, limit=10, include_previous_versions=False):
    return json.dumps(list_documents(session, query, offset, limit, include_previous_versions), ensure_ascii=False)


def read_saved_document(session, message_id, filename, part='document', source_index=0, start_char=0, max_chars=12000):
    from app.agent.source_kinds import source_material_kind
    try:
        record = get_document(session, message_id, filename)
    except LookupError as exc:
        return json.dumps({'error': str(exc)}, ensure_ascii=False)
    if part == 'source':
        sources = record['sources']
        if source_index < 0 or source_index >= len(sources):
            return json.dumps({'error': '来源编号不存在'}, ensure_ascii=False)
        source = sources[source_index]
        text = source.get('excerpt') or source.get('snippet') or ''
        if source.get('source_type') == 'web':
            from app.agent.web_sources import snapshot_result
            result = snapshot_result(source, message_id, source_index)
        else:
            paper = session.get(Paper, source.get('paper_id')) if isinstance(source.get('paper_id'), int) else None
            if paper is None or paper.is_deleted:
                return json.dumps({'error': '该论文已移除，来源不可读取'}, ensure_ascii=False)
            result = {'paper_id': paper.id, 'title': source.get('title') or paper.title,
                      'material_kind': source_material_kind(source),
                      'type': source.get('source_type', 'saved_excerpt'), 'pages': source.get('pages', []),
                      'locator': source.get('locator', ''), 'saved_message_id': message_id, 'source_index': source_index}
    else:
        text = record['content']
        kind = ('research_document' if record.get('adoption_status') == 'not_user_adopted' else
                'user_revision' if record['author'] == 'user' else 'assistant_document')
        result = {**_metadata(record), 'material_kind': kind,
            'note': '这是保存的研究成果，不是论文原文；来源目录可用 part=source 按 source_index 回读。',
            'source_catalog': [{'source_index': i, 'material_kind': source_material_kind(s), **{k: s.get(k) for k in ('paper_id', 'title', 'pages', 'source_type', 'url', 'retrieved_at')}}
                               for i, s in enumerate(record['sources']) if isinstance(s, dict)]}
        if record['newer_versions']:
            result['version_note'] = ('此处仍返回你指定的原版本。newer_versions 列出它的后续修订入口及已有作者、采用状态；'
                                      '继续当前研究时可回读修订稿，历史对照仍可使用原版本。'
                                      '多个入口可能是独立分支，也可能是尚未采用的草稿与此前版本；'
                                      '按已有作者、采用状态和当前问题选择。')
    start = max(0, min(start_char, len(text))); end = min(len(text), start + max(500, min(max_chars, 20000)))
    return json.dumps({**result, 'text': text[start:end], 'start_char': start, 'total_chars': len(text),
                       'next_start_char': end if end < len(text) else None}, ensure_ascii=False)
