"""Bring saved primary passages forward without copying the entire tool transcript."""
import json
from sqlmodel import select
from app.models import Message, Paper
from app.agent.context import estimate_tokens
from app.agent.source_kinds import source_material_kind


def _sources(message):
    try:
        rows = json.loads(message.sources_json or '[]')
    except (ValueError, TypeError):
        return []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def carry_sources(session, conversation_id, current_message_id, paper_ids, token_budget, *, provided_texts=None):
    """Carry whole excerpts from the prior turn; overflow remains addressable by tool."""
    previous = session.exec(select(Message).where(Message.conversation_id == conversation_id,
        Message.id < current_message_id).order_by(Message.id.desc())).first()
    if previous is None or token_budget <= 0:
        return '', []
    header = ('[此前研究中保存的来源]\n以下是此前返回的材料快照；material_kind 区分原文片段、摘要书目、检索线索、生成分析与研究记录。'
              '检索线索用于发现材料，原文片段也不代表已读完整论文；这些快照不是上一版答案的事实背书。'
              '修改或压缩时保留比较条件、作者归因与不确定性；新增判断应说明是你的推断。'
              '不要把未证实解释改成确定结论。材料够用即可直接写；需要其他保存片段时可用 read_chat_sources。\n')
    remaining = token_budget - estimate_tokens(header)
    records, carried = [], []
    # Preserve recent reading before early exploratory material. Reserve the
    # catalog first so one long passage cannot hide the other saved sources.
    rows = list(enumerate(_sources(previous)))
    priority = {'original_text': 0, 'webpage': 1, 'abstract_metadata': 2, 'research_record': 3,
                'generated_analysis': 3, 'unknown': 4, 'discovery': 5}
    rows.sort(key=lambda pair: (priority[source_material_kind(pair[1])],
                               pair[1].get('retrieved_by') == 'initial_retrieval',
                               -pair[0]))
    for index, source in rows:
        pid = source.get('paper_id')
        if source.get('source_type') == 'web':
            record = {key: source.get(key) for key in ('url', 'title', 'retrieved_at', 'snapshot_id', 'source_type')}
        else:
            if not isinstance(pid, int) or isinstance(pid, bool) or (paper_ids is not None and pid not in paper_ids):
                continue
            paper = session.get(Paper, pid)
            if paper is None or paper.is_deleted:
                continue
            record = dict(paper_id=pid, title=source.get('title') or paper.title,
                          source_type=source.get('source_type', 'saved_excerpt'),
                          pages=source.get('pages', []), locator=source.get('locator', ''))
        excerpt = source.get('excerpt') or source.get('snippet')
        if not isinstance(excerpt, str) or not excerpt.strip():
            continue
        # An unchanged primary excerpt already inside this turn's complete
        # paper text need not be copied again as escaped catalog JSON. Changed
        # historical passages, notes and webpages remain available as before.
        if (source_material_kind(source) == 'original_text' and
                isinstance((provided_texts or {}).get(pid), str) and
                excerpt in provided_texts[pid]):
            continue
        record.update(message_id=previous.id, source_index=index, material_kind=source_material_kind(source))
        pointer = json.dumps({**record, 'chars': len(excerpt),
            'note': '目录项，不是原文；可用 read_chat_sources 读取完整摘录'}, ensure_ascii=False)
        cost = estimate_tokens(pointer + '\n')
        if cost <= remaining:
            records.append((source, excerpt, record, pointer, cost)); remaining -= cost
    lines = []
    for source, excerpt, record, pointer, pointer_cost in records:
        full = json.dumps({**record, 'excerpt': excerpt}, ensure_ascii=False)
        extra = estimate_tokens(full + '\n') - pointer_cost
        if extra <= remaining:
            lines.append(full); remaining -= extra
            carried.append({**source, 'carried_from_message': previous.id})
        else:
            lines.append(pointer)
    return (header + '\n'.join(lines), carried) if lines else ('', [])


def read_chat_sources(session, message_id, source_index, start_char=0, max_chars=12000):
    """Read a prior source snapshot in this conversation, not a newer paper revision."""
    conversation_id = session.info.get('chat_conversation_id')
    message = session.get(Message, message_id)
    if conversation_id is None or message is None or message.conversation_id != conversation_id:
        return json.dumps({'error': '当前对话中没有该来源记录'}, ensure_ascii=False)
    rows = _sources(message)
    if not isinstance(source_index, int) or source_index < 0 or source_index >= len(rows):
        return json.dumps({'error': '来源编号不存在'}, ensure_ascii=False)
    source = rows[source_index]
    if source.get('source_type') == 'web':
        from app.agent.web_sources import snapshot_result
        result = snapshot_result(source, message.id, source_index)
    else:
        paper = session.get(Paper, source.get('paper_id')) if isinstance(source.get('paper_id'), int) else None
        if paper is None or paper.is_deleted:
            return json.dumps({'note': '该论文已移除，未将历史摘录重新作为当前研究材料'}, ensure_ascii=False)
        result = dict(paper_id=paper.id, title=source.get('title'),
                      type=source.get('source_type', 'saved_excerpt'),
                      material_kind=source_material_kind(source),
                      pages=source.get('pages', []), locator=source.get('locator', ''))
    text = source.get('excerpt') or source.get('snippet') or ''
    start = max(0, min(int(start_char), len(text)))
    end = min(len(text), start + max(500, min(int(max_chars), 12000)))
    return json.dumps({**result, 'text': text[start:end], 'saved_message_id': message.id,
        'source_index': source_index, 'start_char': start,
        'next_start_char': end if end < len(text) else None, 'total_chars': len(text)}, ensure_ascii=False)
