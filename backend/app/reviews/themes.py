"""Theme proposal and paper assignment for the literature map (A4a)."""
import json
import re

from sqlmodel import Session, select
from app.models import Paper
from app.models.card import PaperCard

PROPOSE = '''你在为研究者整理一批论文的研究路线。下面每行是一篇论文的精读卡片摘要。
请提出 6 到 10 个研究主题，按“解决问题的机制”划分，而不是按期刊、年份或应用领域划分；一篇论文可以属于多个主题。
返回 JSON：{"themes": [{"id": "T1", "name": "不超过 20 字的主题名", "definition": "一句话定义这条研究路线解决什么问题、靠什么机制", "include": "纳入标准", "exclude": "不纳入的情况"}]}
只输出 JSON。'''

MERGE = '''下面是对同一批论文分批提出的主题。请合并含义重复的主题，保留有区别的主题，最终输出 6 到 10 个，格式同上，id 重新编号为 T1、T2……只输出 JSON。'''

ASSIGN = '''主题列表：{themes}
请为下面每篇论文分配 1 到 2 个最贴切的主题 id，并用一句话说明理由。返回 JSON：{"assignments": [{"paper_id": 12, "themes": ["T1"], "reason": "……"}]}
只能使用主题列表中的 id。只输出 JSON。'''

THEME_FIELDS = ('id', 'name', 'definition', 'include', 'exclude')
BATCH_LINES = 60
BATCH_CHARS = 60000
ASSIGN_BATCH = 20


class ThemeError(Exception):
    """Theme proposal failed after its single retry; the only fatal map error."""


def parse_payload(raw):
    """Strip code fences, take the outermost JSON object, return dict or None."""
    text = (raw or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s+```$', '', text).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def valid_themes(data):
    themes = data.get('themes') if isinstance(data, dict) else None
    if not isinstance(themes, list) or not 6 <= len(themes) <= 10:
        return None
    out = []
    for item in themes:
        if not isinstance(item, dict):
            return None
        if not all(isinstance(item.get(name), str) and item[name].strip() for name in THEME_FIELDS):
            return None
        out.append({name: item[name] for name in THEME_FIELDS})
    return out


def card_line(paper_id, card_row, paper) -> str:
    card = json.loads(card_row.card_json) if card_row is not None else {}
    values = {name: ((card.get(name) or {}).get('value') or '').strip()
              for name in ('problem', 'mechanism', 'data_setting')}
    head = f'[P{paper_id}] {paper.year or ""} {paper.title or ""}'
    if card_row is not None and card_row.status in ('done', 'metadata_only') and all(values.values()):
        line = (f'{head} | 问题：{values["problem"]} | 机制：{values["mechanism"]}'
                f' | 数据：{values["data_setting"]}')
    else:
        line = f'{head} | 摘要：{(paper.abstract or "")[:300]}'
    return line[:400]


def card_lines(session: Session, review_id) -> list:
    from app.reviews import service

    ids = [p.paper_id for p in service.papers(session, review_id) if p.status != 'missing']
    card_rows = {r.paper_id: r for r in session.exec(
        select(PaperCard).where(PaperCard.paper_id.in_(ids)))}
    lines = []
    for pid in ids:
        paper = session.get(Paper, pid)
        if paper is None or paper.is_deleted:
            continue
        lines.append(card_line(pid, card_rows.get(pid), paper))
    return lines


def _attempt(ask, system, user):
    return valid_themes(parse_payload(ask(system, user, 4000)))


def propose_themes(ask, lines):
    """Propose 6-10 themes; retry each call once, then raise ThemeError.

    The caller renumbers ids, so batch-local ids never leak out.
    """
    def propose_once(user):
        themes = _attempt(ask, PROPOSE, user)
        if themes is None:
            themes = _attempt(ask, PROPOSE, user)
        if themes is None:
            raise ThemeError('主题提出失败')
        return themes

    total = sum(len(line) + 1 for line in lines)
    if total <= BATCH_CHARS:
        return propose_once('\n'.join(lines))
    proposals = []
    for start in range(0, len(lines), BATCH_LINES):
        proposals.extend(propose_once('\n'.join(lines[start:start + BATCH_LINES])))
    merged = _attempt(ask, MERGE, json.dumps({'themes': proposals}, ensure_ascii=False))
    if merged is None:
        merged = _attempt(ask, MERGE, json.dumps({'themes': proposals}, ensure_ascii=False))
    if merged is None:
        raise ThemeError('主题提出失败')
    return merged


def renumber(themes):
    return [{**theme, 'id': f'T{i + 1}'} for i, theme in enumerate(themes)]


def diff_themes(old, new):
    """Compare theme lists by id; any content field differing counts as changed."""
    old_by_id = {t.get('id'): t for t in old}
    new_by_id = {t.get('id'): t for t in new}
    changed, removed, added = [], [], []
    for tid, theme in new_by_id.items():
        if tid not in old_by_id:
            added.append(tid)
        elif any(theme.get(field) != old_by_id[tid].get(field)
                 for field in ('name', 'definition', 'include', 'exclude')):
            changed.append(tid)
    removed.extend(tid for tid in old_by_id if tid not in new_by_id)
    return {'changed': changed, 'removed': removed, 'added': added}


def assign_batch(ask, themes, lines):
    """Assign one batch of <=20 papers; returns {paper_id: {themes, reason}}.

    Unknown ids are dropped, >2 truncated; papers still missing (or emptied by
    validation) are retried once as their own request, then marked unassigned.
    """
    theme_ids = {t['id'] for t in themes}
    themes_json = json.dumps(themes, ensure_ascii=False)

    def parse(user_payload):
        found = {}
        data = parse_payload(user_payload) or {}
        items = data.get('assignments')
        if not isinstance(items, list):
            return found
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                pid = int(item.get('paper_id'))
            except (TypeError, ValueError):
                continue
            picked = [t for t in item.get('themes') or []
                      if isinstance(t, str) and t in theme_ids][:2]
            reason = item.get('reason')
            found[pid] = {'themes': picked, 'reason': reason if isinstance(reason, str) else ''}
        return found

    def request(batch_lines):
        system = ASSIGN.replace('{themes}', themes_json)
        return system, '\n'.join(batch_lines)

    system, user = request(lines)
    found = parse(ask(system, user, 2000))
    missing = {int(re.match(r'\[P(\d+)\]', line)[1]) for line in lines
               if not found.get(int(re.match(r'\[P(\d+)\]', line)[1]), {}).get('themes')}
    if missing:
        retry_lines = [line for line in lines
                       if int(re.match(r'\[P(\d+)\]', line)[1]) in missing]
        retry_system, retry_user = request(retry_lines)
        for pid, entry in parse(ask(retry_system, retry_user, 2000)).items():
            if entry['themes']:
                found[pid] = entry
    result = {}
    for line in lines:
        pid = int(re.match(r'\[P(\d+)\]', line)[1])
        entry = found.get(pid) or {}
        result[pid] = entry if entry.get('themes') else {'themes': [], 'reason': '未能归类'}
    return result
