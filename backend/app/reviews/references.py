"""Styled reference formatting for review exports (P5a).

Pure GB/T 7714-2015 (numeric) and APA formatters over plain paper dicts, plus
the export-side rewriting of the `## 引用文献` section. No CSL engine
dependency on purpose: these call sites are the replacement seam if a CSL
engine is adopted later. Only `papers_for` touches the database.
"""
import re

from sqlmodel import Session, select

from app.models import Paper
from app.models.paper import parse_authors_json

STYLES = ('gbt', 'apa')

_REF_MARK = re.compile(r'\[P(\d+)\]')
# 假名 / CJK 扩展 A / CJK 统一表意 / 兼容表意 / 谚文：命中即视为中日韩姓名原样保留。
_CJK = re.compile('[\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\uac00-\\ud7af]')
REF_HEADING = '\n## 引用文献'
MATERIAL_HEADING = '\n## 材料范围'


def _check_style(style: str) -> str:
    if style not in STYLES:
        raise ValueError(f'未知的引用著录风格：{style}')
    return style


def _text(value: object) -> str:
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _initials(given: str) -> list[str]:
    return [token[0].upper() for token in given.replace('.', ' ').split()
            if token and token[0].isalpha()]


def format_author(name: str, style: str) -> str:
    """One name; CJK and single-token names pass through unchanged."""
    _check_style(style)
    text = (name or '').strip()
    if not text or _CJK.search(text):
        return text
    if ',' in text:
        surname, given = text.split(',', 1)
        surname, given = surname.strip(), given.strip()
    else:
        tokens = text.split()
        if len(tokens) == 1:
            return text
        surname, given = tokens[-1], ' '.join(tokens[:-1])
    initials = _initials(given)
    if style == 'gbt':
        return ' '.join([surname.upper()] + initials)
    if initials:
        return f"{surname}, {' '.join(initial + '.' for initial in initials)}"
    return surname


def format_authors(names: list[str], style: str) -> str:
    _check_style(style)
    source = [name for name in (names or []) if _text(name)]
    formatted = [name for name in (format_author(n, style) for n in source) if name]
    if not formatted:
        return ''
    if style == 'gbt':
        if len(formatted) > 3:
            etc = '等' if any(_CJK.search(n) for n in source) else 'et al.'
            return ', '.join(formatted[:3]) + f', {etc}'
        return ', '.join(formatted)
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f'{formatted[0]}, & {formatted[1]}'
    if len(formatted) <= 20:
        return ', '.join(formatted[:-1]) + ', & ' + formatted[-1]
    return ', '.join(formatted[:19]) + ', ... ' + formatted[-1]


def _volume_part(paper: dict) -> str:
    volume, issue = _text(paper.get('volume')), _text(paper.get('issue'))
    if volume and issue:
        return f'{volume}({issue})'
    return volume or (f'({issue})' if issue else '')


def _tag(paper: dict, gbt: bool) -> str:
    doi, arxiv = _text(paper.get('doi')), _text(paper.get('arxiv_id'))
    if doi:
        return f'DOI: {doi}.' if gbt else f'https://doi.org/{doi}'
    if arxiv:
        return f'arXiv: {arxiv}.' if gbt else f'arXiv: {arxiv}'
    return ''


def _gbt_tail(paper: dict) -> str:
    """`Venue, 年, 卷(期): 页` plus the DOI/arXiv tag; empty segments drop out."""
    meta = ', '.join(part for part in (_text(paper.get('year')), _volume_part(paper)) if part)
    pages = _text(paper.get('pages'))
    if pages:
        meta = f'{meta}: {pages}' if meta else pages
    base = ', '.join(part for part in (_text(paper.get('venue')), meta) if part)
    tag = _tag(paper, gbt=True)
    if base and tag:
        return f'{base}. {tag}'
    if base:
        return base + '.'
    return tag


def _gbt_reference(paper: dict, index: int | None) -> str:
    segments = []
    authors = format_authors(paper.get('authors') or [], 'gbt')
    if authors:
        segments.append(authors if authors.endswith('.') else authors + '.')
    title = _text(paper.get('title'))
    if title:
        segments.append(f'{title}[J].')
    tail = _gbt_tail(paper)
    if tail:
        segments.append(tail)
    if not segments:
        return ''
    prefix = f'[{index}] ' if index is not None else ''
    return prefix + ' '.join(segments)


def _apa_tail(paper: dict) -> str:
    source = ', '.join(part for part in (_text(paper.get('venue')), _volume_part(paper),
                                         _text(paper.get('pages'))) if part)
    tag = _tag(paper, gbt=False)
    if source and tag:
        return f'{source}. {tag}'
    return source + '.' if source else tag


def _apa_reference(paper: dict) -> str:
    segments = []
    authors = format_authors(paper.get('authors') or [], 'apa')
    year = _text(paper.get('year')) or 'n.d.'
    title = _text(paper.get('title'))
    if authors:
        segments.append(f'{authors} ({year}).')
        if title:
            segments.append(title + '.')
    else:
        # 无作者时从题名开始，年份随后。
        if title:
            segments.append(title + '.')
        segments.append(f'({year}).')
    tail = _apa_tail(paper)
    if tail:
        segments.append(tail)
    return ' '.join(segments)


def format_reference(paper: dict, style: str, index: int | None = None) -> str:
    """One entry; `index` only adds the GB/T `[n] ` prefix (APA ignores it)."""
    _check_style(style)
    row = paper or {}
    if style == 'gbt':
        return _gbt_reference(row, index)
    return _apa_reference(row)


def first_appearance_ids(content: str) -> list[int]:
    ids: list[int] = []
    for match in _REF_MARK.finditer(content or ''):
        pid = int(match.group(1))
        if pid not in ids:
            ids.append(pid)
    return ids


def papers_for(session: Session, ids: list[int]) -> dict[int, dict]:
    """Load cited papers into the formatter's plain-dict shape (only DB access)."""
    wanted = sorted({int(pid) for pid in ids})
    if not wanted:
        return {}
    rows = session.exec(select(Paper).where(Paper.id.in_(wanted))).all()
    return {
        row.id: {
            'title': row.title,
            'authors': parse_authors_json(row.authors_json),
            'year': row.year,
            'venue': row.venue,
            'volume': row.volume,
            'issue': row.issue,
            'pages': row.pages,
            'doi': row.doi,
            'arxiv_id': row.arxiv_id,
        }
        for row in rows
    }


def render_styled_markdown(content: str, papers: dict[int, dict], style: str) -> str:
    """Renumber body `[Pn]` marks by first appearance and rebuild the reference list."""
    _check_style(style)
    body, marker, rest = content.partition(REF_HEADING)
    materials = ''
    if marker:
        cut = rest.find(MATERIAL_HEADING)
        if cut != -1:
            materials, rest = rest[cut:], rest[:cut]
    else:
        body = content
        cut = body.find(MATERIAL_HEADING)
        if cut != -1:
            materials, body = body[cut:], body[:cut]
    ordered = [pid for pid in first_appearance_ids(body) if pid in papers]
    numbers = {pid: n for n, pid in enumerate(ordered, start=1)}
    for pid, n in numbers.items():
        body = body.replace(f'[P{pid}]', f'[{n}]')
    if ordered:
        lines = [format_reference(papers[pid], style, index=numbers[pid]) for pid in ordered]
    else:
        lines = ['(正文未引用论文)']
    rendered = body.rstrip('\n') + '\n\n## 引用文献\n\n' + '\n'.join(lines)
    if materials:
        rendered += '\n\n' + materials.lstrip('\n')
    return rendered
