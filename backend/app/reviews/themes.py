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

SYNTHESIZE_THEME = '''你在为研究者撰写文献地图中一个研究主题的分析。材料是该主题下论文的精读卡片和程序统计的数字。
要求：
1. trend：两到四句，说明这条路线的问题和机制怎样演变；涉及数量时只能使用给出的统计数字。
2. open_questions：3 到 5 条值得研究的问题。每条要具体到机制或验证条件，说明为什么现有论文还没有回答，并写出“据现有证据不能宣称什么”。
3. combination_opportunities：2 到 4 条方法组合或迁移机会：把本主题中的某个机制与另一篇论文的机制或另一种数据条件结合，说明预期解决什么、主要风险是什么。
4. representative：3 到 6 篇代表论文及入选理由（开创、实测验证、代表性改进等）。
每条都要在 cards 中列出依据的论文编号（数字），只能使用材料中出现的编号。
返回 JSON：{"trend": "...", "open_questions": [{"question": "...", "why": "...", "cannot_claim": "...", "cards": [12, 30]}], "combination_opportunities": [{"idea": "...", "expected": "...", "risk": "...", "cards": [5, 41]}], "representative": [{"paper_id": 12, "why": "..."}]}
只输出 JSON。'''

OVERVIEW = '''下面是一份文献地图中各研究主题的分析（含趋势、值得研究的问题、代表论文）和全局统计。
请写：
1. summary：一段话（150 到 300 字）总结这批文献反映的前沿格局：主要路线、证据集中在什么条件下、整体缺口在哪里。只使用给出的统计数字。
2. reading_route：3 到 5 步建议阅读路线，从理解基本问题到前沿方法，每步写目标、2 到 5 篇论文编号和理由。
3. research_steps：3 到 6 条从这些材料出发开展新研究的建议步骤（例如先复现哪类基线、用什么数据条件验证、怎样避免只在合成数据上成立的结论）。
只能使用材料中出现的论文编号。
返回 JSON：{"summary": "...", "reading_route": [{"step": 1, "goal": "...", "papers": [3, 8], "why": "..."}], "research_steps": ["..."]}
只输出 JSON。'''

FIELD_MARKERS = ('实测', '现场', 'field', 'real data', 'ocean-bottom', 'obn', 'obc', 'case study')
SYNTHETIC_MARKERS = ('合成', 'synthetic', 'numerical', 'marmousi', 'overthrust')
THEME_FIELDS = ('id', 'name', 'definition', 'include', 'exclude')
BATCH_LINES = 60
BATCH_CHARS = 60000
ASSIGN_BATCH = 20
SYNTH_FULL_CARDS = 40


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


def theme_stats(members):
    """Program-computed counts; the model only explains, never invents numbers."""
    years, setting = {}, {'field': 0, 'synthetic': 0, 'both': 0, 'unknown': 0}
    evidence = {'full_text': 0, 'abstract': 0, 'metadata': 0}
    for member in members:
        year = member.get('year')
        key = str(year) if year else '未知'
        years[key] = years.get(key, 0) + 1
        text = str(member.get('data_setting_value') or '').lower()
        is_field = any(marker in text for marker in FIELD_MARKERS)
        is_synthetic = any(marker in text for marker in SYNTHETIC_MARKERS)
        if is_field and is_synthetic:
            setting['both'] += 1
        elif is_field:
            setting['field'] += 1
        elif is_synthetic:
            setting['synthetic'] += 1
        else:
            setting['unknown'] += 1
        level = member.get('evidence_level')
        if level in evidence:
            evidence[level] += 1
    return {'count': len(members), 'years': dict(sorted(years.items())),
            'setting': setting, 'evidence': evidence}


def validate_synthesis(data, member_ids, review_ids):
    """Drop ids outside the review, require representatives to be members."""
    if not isinstance(data, dict):
        return None

    def as_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    member_set, review_set = set(member_ids), set(review_ids)

    def clean_entries(items, fields):
        out = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            entry = {name: str(item.get(name) or '') for name in fields}
            cards = [as_int(value) for value in item.get('cards') or []]
            cards = [value for value in cards if value in review_set]
            if cards:
                entry['cards'] = cards
            else:
                entry['cards'] = []
                entry['source_missing'] = True  # 界面显示“来源待补”
            out.append(entry)
        return out

    result = {'trend': str(data.get('trend') or '')}
    result['open_questions'] = clean_entries(data.get('open_questions'),
                                             ('question', 'why', 'cannot_claim'))
    result['combination_opportunities'] = clean_entries(data.get('combination_opportunities'),
                                                        ('idea', 'expected', 'risk'))
    representative = []
    for item in data.get('representative') if isinstance(data.get('representative'), list) else []:
        if not isinstance(item, dict):
            continue
        pid = as_int(item.get('paper_id'))
        if pid in member_set:
            representative.append({'paper_id': pid, 'why': str(item.get('why') or '')})
    result['representative'] = representative
    if not any(result.values()):
        return None  # 形同空壳，按解析失败重试
    return result


def validate_overview(data, review_ids):
    """Drop ids outside the review; keep emptied route steps as source_missing."""
    if not isinstance(data, dict):
        return None

    def as_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    review_set = set(review_ids)
    route = []
    items = data.get('reading_route') if isinstance(data.get('reading_route'), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        papers = [as_int(value) for value in item.get('papers') or []]
        papers = [value for value in papers if value in review_set]
        entry = {'step': as_int(item.get('step')) or len(route) + 1,
                 'goal': str(item.get('goal') or ''), 'why': str(item.get('why') or '')}
        if papers:
            entry['papers'] = papers
        else:
            entry['papers'] = []
            entry['source_missing'] = True
        route.append(entry)
    steps = data.get('research_steps') if isinstance(data.get('research_steps'), list) else []
    result = {'summary': str(data.get('summary') or ''), 'reading_route': route,
              'research_steps': [str(step) for step in steps if isinstance(step, str)]}
    if not result['summary'] and not route and not result['research_steps']:
        return None
    return result


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
