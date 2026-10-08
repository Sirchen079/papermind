"""Navigate recorded document inputs without promoting them to primary evidence."""
import json

from app.agent.document_revisions import public_revision
from app.models import Message


def _object(value):
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def document_inputs(session, message_id, filename):
    from app.agent.saved_documents import _records, generation_origin, generating_user_turn

    origin, target_name = generation_origin(session, message_id, filename)
    current = session.get(Message, message_id)
    entries = {}

    def add(reference, relation, read=None):
        if not isinstance(reference, dict):
            return
        mid, name = reference.get('message_id'), reference.get('filename')
        if type(mid) is not int or mid <= 0 or mid >= message_id or not isinstance(name, str) or not name:
            return
        key = (mid, name)
        entry = entries.setdefault(key, {'message_id': mid, 'filename': name, 'relations': [], 'reads': []})
        if relation not in entry['relations']:
            entry['relations'].append(relation)
        if read is not None and read not in entry['reads']:
            entry['reads'].append(read)

    revision = public_revision(current) if current else None
    if revision and revision.get('parent_message_id'):
        add({'message_id': revision['parent_message_id'], 'filename': revision.get('parent_filename')}, 'revision_parent')
    request = generating_user_turn(session, origin)
    for item in _object(request.request_json if request else None).get('attachments', []):
        if isinstance(item, dict) and item.get('kind') == 'text':
            add(item.get('saved_document'), 'attached')

    tools = _object(origin.agent_state_json if origin else None).get('tools', [])
    # An answer may save several files and perform more reads afterwards. Only
    # reads preceding this exact saved artifact belong in its input history.
    if target_name is not None:
        saves = [i for i, tool in enumerate(tools) if tool.get('name') == 'save_document'
                 and tool.get('ok') and _object(tool.get('result')).get('ok') is True
                 and _object(tool.get('result')).get('filename') == target_name]
        tools = tools[:saves[-1]] if saves else []
    for tool in tools:
        if tool.get('name') != 'read_saved_document' or not tool.get('ok'):
            continue
        args = tool.get('args') or {}
        result = _object(tool.get('result'))
        if result.get('error') or result.get('ok') is False:
            continue
        part = args.get('part', 'document')
        count = result.get('loaded_chars', len(result.get('text', '')))
        returned_id = result.get('saved_message_id') if part == 'source' else result.get('message_id')
        confirmed = (type(count) is int and count > 0 and returned_id == args.get('message_id')
                     and (part == 'source' or result.get('filename') == args.get('filename')))
        read = None
        if confirmed:
            read = {'part': part, 'start_char': result.get('start_char', 0), 'loaded_chars': count}
            if part == 'source':
                read['source_index'] = result.get('source_index', args.get('source_index', 0))
        # Older public results were cut mid-JSON. Retain the navigation target,
        # but label the historical attempt separately from a confirmed read.
        add(args, 'read' if confirmed else 'read_unconfirmed', read)

    for entry in entries.values():
        record = next((r for r in _records(session, entry['message_id']) if r['filename'] == entry['filename']), None)
        entry['available'] = record is not None
        if record:
            entry.update({key: record[key] for key in ('conversation_id', 'conversation_title', 'author', 'created_at')})
    return list(entries.values())
