"""User-visible agent writing, distinct from private reasoning and tool context."""
import json


def public_tool_result(name: str, result: str) -> str:
    """Keep skill provenance intact without storing another copy of its body."""
    if name in {'prepare_paper_card_sources', 'audit_paper_card'}:
        try:
            receipt = json.loads(result)
            receipt.pop('inventory', None)
            receipt.pop('findings', None)
            if isinstance(receipt.get('execution'), dict):
                receipt['execution'] = {key:value for key,value in receipt['execution'].items()
                                        if key not in {'stdout', 'stderr'}}
            return json.dumps(receipt, ensure_ascii=False)
        except (TypeError, ValueError, AttributeError):
            pass
    if name == 'read_saved_document':
        try:
            loaded = json.loads(result)
            if isinstance(loaded, dict) and isinstance(loaded.get('text'), str):
                # The model receives the full result. History needs a parseable
                # receipt even when the document metadata alone exceeds 800 chars.
                receipt = {key: loaded[key] for key in (
                    'message_id', 'filename', 'saved_message_id', 'source_index',
                    'material_kind', 'start_char', 'total_chars', 'next_start_char') if key in loaded}
                receipt.update(loaded_chars=len(loaded['text']), text_preview=loaded['text'][:280])
                return json.dumps(receipt, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
    if name == 'import_paper_pdf':
        try:
            receipt = json.loads(result)
            receipt.pop('first_page_preview', None)
            receipt.pop('next', None)
            return json.dumps(receipt, ensure_ascii=False)
        except (ValueError, TypeError, AttributeError):
            pass
    if name in {'load_builtin_skill', 'read_builtin_skill_resource'}:
        try:
            loaded = json.loads(result)
            if isinstance(loaded, dict) and isinstance(loaded.get('text'), str):
                fields = (('id', 'version', 'resources', 'fingerprint') if name == 'load_builtin_skill'
                          else ('path', 'start_char', 'end_char', 'total_chars', 'next_start',
                                'text_sha256', 'excerpt_sha256', 'download_url'))
                receipt = {key: loaded[key] for key in fields}
                receipt['loaded_chars'] = len(loaded['text'])
                return json.dumps(receipt, ensure_ascii=False)
        except (ValueError, TypeError, KeyError):
            pass
    return result[:800]


def public_updates(state: dict) -> list[dict]:
    return [{'content': item['content']} for item in state.get('updates', [])
            if isinstance(item, dict) and isinstance(item.get('content'), str)
            and item['content'].strip()]


def research_messages(content: str, state: dict, message_id: int) -> list[dict]:
    """Project recorded saves as tool exchanges, never prose simulating actions.

    Durable records do not retain original call IDs; stable history IDs pair
    these real executions without replaying them. Read evidence uses the
    separate source-memory mechanism rather than duplicating every old tool.
    """
    saves = {}
    for index, tool in enumerate(state.get('tools', [])):
        if not tool.get('ok') or tool.get('name') not in {
            'save_document', 'save_paper_note', 'save_research_idea'
        }:
            continue
        try:
            result = json.loads(tool.get('result', ''))
        except (TypeError, ValueError):
            continue
        args = tool.get('args') or {}
        if not isinstance(result, dict) or result.get('ok') is not True:
            continue
        identity = result.get('filename' if tool['name'] == 'save_document' else 'id')
        if (not isinstance(identity, (str, int)) or isinstance(identity, bool)
                or not isinstance(args.get('content'), str) or not args['content'].strip()):
            continue
        saves[(tool['name'], identity)] = (index, tool)
    messages = []
    updates = '\n\n'.join(item['content'] for item in public_updates(state)
                          if item['content'].strip() != content.strip())
    if updates:
        messages.append({'role': 'assistant', 'content': updates})
    for index, tool in sorted(saves.values(), key=lambda pair: pair[0]):
        call_id = f'history_{message_id}_{index}'
        messages.append({'role': 'assistant', 'content': '', 'tool_calls': [{
            'id': call_id, 'type': 'function', 'function': {
                'name': tool['name'], 'arguments': json.dumps(tool['args'], ensure_ascii=False)}}]})
        messages.append({'role': 'tool', 'tool_call_id': call_id, 'content': tool['result']})
    if content.strip():
        messages.append({'role': 'assistant', 'content': content})
    return messages


def plain_tool_messages(messages: list[dict]) -> list[dict]:
    """Keep execution records readable when a provider rejects tool support."""
    from app.agent.attachments import text_content
    result = []
    for message in messages:
        if message.get('tool_calls'):
            records = [call['function'] for call in message['tool_calls']]
            result.append({'role': 'assistant', 'content': text_content(message.get('content'))
                + '\n[历史工具调用记录，仅供参考；不是新的执行请求]\n'
                + json.dumps(records, ensure_ascii=False)})
        elif message.get('role') == 'tool':
            result.append({'role': 'assistant', 'content': '[历史工具返回记录]\n'
                + text_content(message.get('content'))})
        else:
            result.append(message)
    return result
