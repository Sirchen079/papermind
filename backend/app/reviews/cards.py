"""Paper-level structured reading cards with programmatically verifiable quotes."""
import json
import re

from sqlmodel import Session, select
from app.models import Paper
from app.models.base import utcnow
from app.models.card import PaperCard
from app.models.paper import parse_authors_json
from app.reviews.service import digest
from app.reviews.structured import ModelUnavailable, StructuredAsker, model_window

CARD_PROMPT = '''你在为研究者制作一张论文精读卡片。只依据给出的材料，用中文填写，不写材料里没有的内容。
返回一个 JSON 对象，不要输出其他文字：
{
 "problem": {"value": "本文要解决的具体问题，一句话", "quote": "支撑它的原文句子"},
 "mechanism": {"value": "方法的关键机制，说明与常规做法的区别，一到两句", "quote": "原文句子"},
 "data_setting": {"value": "验证条件：合成/实测、二维/三维、模型或工区名称", "quote": "原文句子"},
 "contributions": [{"value": "主要贡献，一句话；含数值时写明数据集和指标", "quote": "原文句子"}],
 "boundary": {"value": "引用本文结论前还需要核对什么、不能据此宣称什么", "quote": "原文句子；属于你的判断时留空"}
}
要求：contributions 写 1 到 3 条。quote 必须从材料中逐字复制一句英文或中文原文，不翻译、不改写、不拼接；找不到合适原句时 quote 留空字符串。value 中出现的数字必须出现在对应的 quote 里。'''

SNIPPET_QUERIES = ('method approach proposed', 'data experiment field synthetic', 'limitation however future work')
CARD_FIELDS = ('problem', 'mechanism', 'data_setting', 'boundary')
# build_card turns provider exceptions into fallback cards whose warning starts
# with the exception type name; parse failures carry a Chinese message instead.
_EXCEPTION_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_.]*$')


def _exception_warning(exc: Exception) -> str:
    return f'{type(exc).__name__}: {str(exc)[:120]}'


def card_inputs(session: Session, paper: Paper) -> dict:
    """Program-assembled model inputs; metadata never depends on the model."""
    metadata = {
        'title': paper.title,
        'authors': parse_authors_json(paper.authors_json),
        'year': paper.year,
        'venue': paper.venue,
        'doi': paper.doi,
        'links': [f'https://doi.org/{paper.doi}'] if paper.doi else [],
    }
    snippets = ''
    if paper.full_text:
        from app.rag.scalable import hybrid

        parts = []
        seen = set()
        try:
            for query in SNIPPET_QUERIES:
                for chunk in hybrid(session, query, [paper.id], k=2):
                    if chunk.id in seen or chunk.ordinal == 0:
                        continue
                    seen.add(chunk.id)
                    parts.append(chunk.text)
        except Exception:
            parts = []
        snippets = '\n\n'.join(parts)[:3000]
    evidence_level = 'full_text' if paper.full_text else ('abstract' if paper.abstract else 'metadata')
    return {'metadata': metadata, 'abstract': paper.abstract or '', 'snippets': snippets,
            'evidence_level': evidence_level}


def card_fingerprint(inputs: dict, model: str) -> str:
    return digest([inputs, CARD_PROMPT, model, 'card-v1'])


def parse_card(raw: str) -> dict | None:
    """Strict shape check; malformed output is retried once, then falls back."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    def entry(value):
        if isinstance(value, dict) and isinstance(value.get('value'), str) and value['value'].strip():
            quote = value.get('quote')
            return {'value': value['value'], 'quote': quote if isinstance(quote, str) else ''}
        return None

    card = {}
    for name in CARD_FIELDS:
        parsed = entry(data.get(name))
        if parsed is None:
            return None
        card[name] = parsed
    raw_contributions = data.get('contributions')
    if not isinstance(raw_contributions, list):
        return None
    contributions = [parsed for parsed in (entry(item) for item in raw_contributions) if parsed]
    if not contributions:
        return None
    card['contributions'] = contributions[:3]
    return card


def _verified_field(field: dict | None, sources: dict, metadata_only: bool) -> dict:
    item = dict(field or {})
    if metadata_only:
        item.update(status='unverifiable', found_in=None, pages=[], missing_numbers=[])
        return item
    from app.reviews.verify import check_field

    result = check_field(item.get('value') or '', item.get('quote') or '', sources)
    item.update(status=result['status'], found_in=result['found_in'], pages=result['pages'],
                missing_numbers=result['missing_numbers'])
    return item


def verify_card(card: dict, inputs: dict, full_text: str | None) -> dict:
    """Attach deterministic quote/number verification to every content field."""
    sources = {'abstract': inputs.get('abstract') or '', 'snippets': inputs.get('snippets') or '',
               'full_text': full_text or ''}
    metadata_only = inputs.get('evidence_level') == 'metadata'
    verified = {name: _verified_field(card.get(name), sources, metadata_only) for name in CARD_FIELDS}
    verified['contributions'] = [_verified_field(item, sources, metadata_only)
                                 for item in card.get('contributions', [])]
    return verified


def build_card(session: Session, paper: Paper, complete) -> dict:
    """Build one card; the injected ``complete(system, user)`` keeps tests offline."""
    inputs = card_inputs(session, paper)
    base = {'metadata': inputs['metadata'], 'evidence_level': inputs['evidence_level']}
    if inputs['evidence_level'] == 'metadata':
        return {'status': 'metadata_only', 'card': base, 'warning': ''}
    user = json.dumps({'metadata': inputs['metadata'], 'abstract': inputs['abstract'],
                       'snippets': inputs['snippets']}, ensure_ascii=False)
    try:
        parsed = parse_card(complete(CARD_PROMPT, user))
        if parsed is None:
            parsed = parse_card(complete(CARD_PROMPT, user + '\n上次输出不是合法 JSON，请只输出 JSON 对象。'))
    except ModelUnavailable:
        raise
    except Exception as exc:
        return {'status': 'fallback', 'card': base, 'warning': _exception_warning(exc)}
    if parsed is None:
        return {'status': 'fallback', 'card': base, 'warning': '卡片格式解析失败，保留元数据'}
    card = {**verify_card(parsed, inputs, paper.full_text), **base}
    return {'status': 'done', 'card': card, 'warning': ''}


def save_card(session: Session, paper_id: int, fingerprint: str, result: dict, model: str) -> None:
    row = session.exec(select(PaperCard).where(PaperCard.paper_id == paper_id)).first()
    if row is None:
        row = PaperCard(paper_id=paper_id)
    row.fingerprint = fingerprint
    row.status = result['status']
    row.card_json = json.dumps(result['card'], ensure_ascii=False)
    row.model = model
    row.warning = result.get('warning') or ''
    row.version += 1
    row.updated_at = utcnow()
    session.add(row)
    session.commit()


def ensure_cards(engine, paper_ids, client, provider, model, ref_id, active, warnings) -> dict:
    """Build or reuse paper cards alongside a review (and later the map flow).

    Cards are paper-level reading aids: they never feed synthesis or writing
    and are not part of any generation key. One paper's failure only appends a
    warning; the surrounding task always continues. Consecutive provider
    failures abort the pool quietly (no raise) via ``unavailable``.
    """
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from contextvars import copy_context

    with Session(engine) as s:
        window = model_window(s, provider, model)
    asker = StructuredAsker(client, provider, model, ref_id=ref_id, window=window)

    def complete(system, user):
        return asker.ask(system, user, 2000)

    def build_one(pid):
        with Session(engine) as s:
            paper = s.get(Paper, pid)
            if paper is None or paper.is_deleted:
                return None
            inputs = card_inputs(s, paper)
            fingerprint = card_fingerprint(inputs, model)
            row = s.exec(select(PaperCard).where(PaperCard.paper_id == pid)).first()
            if row and row.fingerprint == fingerprint and row.status in {'done', 'metadata_only'}:
                return None
            result = build_card(s, paper, complete)
            save_card(s, pid, fingerprint, result, model)
            return result

    counts = {'done': 0, 'fallback': 0, 'metadata_only': 0, 'skipped': 0}
    unavailable = ''
    iterator = iter(paper_ids)
    finished = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {}

        def submit():
            pid = next(iterator, None)
            if pid is not None and not unavailable:
                pending[pool.submit(copy_context().run, build_one, pid)] = pid

        for _ in range(3):
            submit()
        while pending:
            done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            if not active():
                break
            for future in done:
                pending.pop(future)
                finished += 1
                try:
                    result = future.result()
                    if result is None:
                        counts['skipped'] += 1
                        continue
                    counts[result['status']] = counts.get(result['status'], 0) + 1
                    if (result['status'] == 'fallback'
                            and _EXCEPTION_NAME.match((result.get('warning') or '').split(':', 1)[0])):
                        warnings.append(f'第 {finished} 篇精读卡片未生成（{result["warning"]}）')
                except ModelUnavailable as exc:
                    if not unavailable:
                        unavailable = str(exc)
                except Exception as exc:
                    warnings.append(f'第 {finished} 篇精读卡片未生成（{type(exc).__name__}）')
            if active():
                submit()
    if unavailable:
        warnings.append('模型连续调用失败，其余论文的精读卡片未生成')
    return {**counts, 'unavailable': unavailable}
