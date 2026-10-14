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
MATERIAL_HEADING = '\n## 材料范围'
# 文献节标题：标题文本恰为「引用文献」的二级 ATX 标题（围栏内/行中同名文本不算）。
_REF_HEADING_TITLE = '引用文献'
# 围栏开启：≥3 个连续 ` 或 ~；反引号围栏的信息串不得再含反引号（CommonMark）。
_FENCE_OPEN = re.compile('(`{3,}|~{3,})')
# ATX 标记：1-6 个 # 后须跟空白或行尾，`#标签` 之类的行内文本不是标题。
_ATX_MARK = re.compile('(#{1,6})(?=[ \\t]|$)')


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


# APA 作者—年份文内引用（第 7 版规则）：1 名作者用姓氏，2 名用 A & B，
# 3 名及以上用「A et al.」；无作者以题名代替；无年份记 n.d.（§8.17）。
def _apa_surname(name: str) -> str:
    """文内引用只用姓氏；复用 format_author 的解析（CJK 与单词名原样保留）。"""
    return format_author(name, 'apa').split(',')[0].strip()


def _apa_surnames(paper: dict) -> list[str]:
    return [surname for surname in (_apa_surname(n) for n in paper.get('authors') or [])
            if surname]


_LEADING_ARTICLE = re.compile('^(?:a|an|the)\\s+', re.IGNORECASE)


def _apa_title_key(paper: dict) -> str:
    """题名排序键（小写、忽略冠词）；无作者条目按题名参与排序（§9.44）。"""
    return _LEADING_ARTICLE.sub('', _text(paper.get('title')).lower())


def _apa_year_key(paper: dict) -> tuple:
    """同作者按年份升序，无年份在最前（§9.44）。"""
    year = _text(paper.get('year'))
    if not year:
        return (0, 0, '')
    try:
        return (1, int(year), '')
    except ValueError:
        return (2, 0, year)


def _apa_sort_key(paper: dict) -> tuple:
    """列表顺序：全体作者姓氏字母序（单作者天然排前），随后年份、题名（§9.44–9.46）。

    姓氏序列整体作为一个元素，避免不同作者人数的键在年份位上跨类型比较。
    """
    surnames = tuple(surname.lower() for surname in _apa_surnames(paper))
    head = (surnames,) if surnames else ((_apa_title_key(paper),),)
    return head + (_apa_year_key(paper), _apa_title_key(paper))


def _apa_in_text_authors(paper: dict) -> str:
    surnames = _apa_surnames(paper)
    if not surnames:
        return _text(paper.get('title'))
    if len(surnames) == 1:
        return surnames[0]
    if len(surnames) == 2:
        return f'{surnames[0]} & {surnames[1]}'
    return f'{surnames[0]} et al.'


# —— 文内消歧三规则（APA 7 §8.18–8.20；Purdue OWL In-Text Citations: Author/Authors）：
# 同一完整作者组同年多篇 → 年份字母 a/b；不同作者组缩写碰撞（同首作者）→ 展开足够
# 多的后续姓氏再加 et al.；同姓不同人 → 首作者加名首字母，首字母再撞则用全名。——
def _apa_name_parts(name: str) -> tuple[str, str]:
    """(姓氏, 名) 拆分，与 format_author 同规则；CJK 与单词名没有名。"""
    text = (name or '').strip()
    if not text or _CJK.search(text):
        return text, ''
    if ',' in text:
        surname, given = text.split(',', 1)
        return surname.strip(), given.strip()
    tokens = text.split()
    if len(tokens) == 1:
        return text, ''
    return tokens[-1], ' '.join(tokens[:-1])


def _apa_author_parts(paper: dict) -> list[tuple[str, str]]:
    return [parts for parts in (_apa_name_parts(n) for n in paper.get('authors') or [])
            if parts[0]]


def _apa_identity(paper: dict) -> tuple:
    """完整作者组身份：(姓氏, 名) 序列（名按小写比较）；同姓不同人、乃至首字母
    相同而名不同的人都不相同。"""
    return tuple((surname, given.lower()) for surname, given in _apa_author_parts(paper))


def _apa_author_display(part: tuple[str, str], initials: bool = False,
                        given_full: bool = False) -> str:
    surname, given = part
    if not given:
        return surname
    if given_full:
        return f'{given} {surname}'
    if initials:
        return ' '.join([mark + '.' for mark in _initials(given)] + [surname])
    return surname


def _apa_form(parts: list[tuple[str, str]], shown: int, first_initials: bool = False,
              first_full: bool = False) -> str:
    """列举前 shown 位作者的文内作者部分：仍有剩余才用 et al.（et al. 至少替代
    两人，全列时不带）；两名作者总是全部列出。首作者可按需加名首字母或全名。"""
    if not parts:
        return ''
    if len(parts) == 2:
        shown = max(shown, 2)
    heads = [_apa_author_display(part, index == 0 and first_initials,
                                 index == 0 and first_full)
             for index, part in enumerate(parts[:shown])]
    if len(parts) == 1:
        return heads[0]
    if shown >= len(parts):
        if len(parts) == 2:
            return f'{heads[0]} & {heads[1]}'
        return ', '.join(heads[:-1]) + ', & ' + heads[-1]
    if shown == 1:
        return heads[0] + ' et al.'
    return ', '.join(heads) + ', et al.'


def _apa_disambiguated_forms(pids: list[int], papers: dict[int, dict]) -> dict[int, str]:
    """同一「默认文内形式 + 年份」碰撞组内各条目的消歧形式；组内只有单一完整
    作者组（该走年份字母规则）时返回 {}。

    首作者为同一人 → 展开后续姓氏至可区分（§8.18）；首作者同姓不同人 → 首作者
    加名首字母，首字母也相同再退到全名（§8.20）；连全名也无法区分（同名同姓）
    时保持原形式、由年份字母兜底——记录为边界。
    """
    parts = {pid: _apa_author_parts(papers[pid]) for pid in pids}
    identities = {pid: _apa_identity(papers[pid]) for pid in pids}
    if len(set(identities.values())) == 1:
        return {}
    if len({identities[pid][:1] for pid in pids}) == 1:
        tries = [(shown, False, False)
                 for shown in range(2, max(map(len, parts.values())) + 1)]
        tries += [(1, True, False), (1, False, True)]
    else:
        tries = [(1, True, False), (1, False, True)]
    for shown, first_initials, first_full in tries:
        forms = {pid: _apa_form(parts[pid], shown, first_initials, first_full)
                 for pid in pids}
        if len(set(forms.values())) == len(set(identities.values())):
            return forms
    return {}


def _apa_entries(ordered: list[int], papers: dict[int, dict]) -> tuple[dict[int, str], list[str]]:
    """作者—年份映射：文内引用与列表条目共用同一套映射。

    年份字母的分组键是**完整作者组身份 + 年份**（§8.19），不再是「文内缩写形式
    + 年份」——旧键会把不同作者组碰巧缩写成同一 et al. 的情况误当同组同年。同一
    完整作者组同年的不同作品按列表顺序追加 a/b（组内顺序由题名或第二作者字母序
    决定，§9.47），正文与列表后缀一致；不同作者组缩写碰撞先展开消歧再判重，列表
    条目不因此加年份字母。返回 (pid → 文内引用, APA 顺序的列表条目)。
    """
    rows = sorted(((_apa_sort_key(papers[pid]), pid) for pid in ordered))
    years = {pid: _text(papers[pid].get('year')) or 'n.d.' for _, pid in rows}
    groups: dict[tuple[str, str], list[int]] = {}
    for _, pid in rows:
        groups.setdefault((_apa_in_text_authors(papers[pid]), years[pid]), []).append(pid)
    forms: dict[int, str] = {}
    for pids in groups.values():
        forms.update(_apa_disambiguated_forms(pids, papers))
    for _, pid in rows:
        forms.setdefault(pid, _apa_in_text_authors(papers[pid]))
    sizes: dict[tuple[str, str], int] = {}
    for _, pid in rows:
        group = (forms[pid], years[pid])
        sizes[group] = sizes.get(group, 0) + 1
    seen: dict[tuple[str, str], int] = {}
    marks: dict[int, str] = {}
    lines = []
    for _, pid in rows:
        author = forms[pid]
        year = years[pid]
        nth = seen.get((author, year), 0)
        seen[(author, year)] = nth + 1
        if sizes[(author, year)] > 1:
            letter = chr(ord('a') + nth)
            year = f'{year}-{letter}' if year == 'n.d.' else f'{year}{letter}'
        marks[pid] = f'({author}, {year})'
        lines.append(format_reference(dict(papers[pid], year=year), 'apa'))
    return marks, lines


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


def _atx_heading(line: str) -> tuple[int, str] | None:
    """行的 ATX 标题 `(级别, 文本)`；≤3 空格缩进合法，4+ 空格是缩进代码块非标题。"""
    rest = line.lstrip(' ')
    if len(line) - len(rest) > 3:
        return None
    mark = _ATX_MARK.match(rest)
    if mark is None:
        return None
    return len(mark.group(1)), rest[mark.end():].strip()


def _ref_section_bounds(content: str) -> tuple[int, int] | None:
    """真实 `## 引用文献` 节的边界 `(标题行起点, 节终点)`，无文献节返回 None。

    逐行扫描并按 CommonMark 规则跳过代码围栏（`app.rag.markdown_chunker`、
    `app.reports.pptx` 的围栏习惯更宽松，这里需要更强的边界保证）：开围栏记录
    完整的字符与长度，闭合围栏须同一字符、个数不小于开启长度，行内其余内容
    不参与判定；反引号开围栏的信息串不得再含反引号。因此四反引号外层围栏内
    的三反引号与字面量标题不会被误判，围栏内及行中同名标题也不是文献节。
    起点是标题行自身（正文以其前一行为止，标题行由渲染统一重排），合法缩进
    标题（≤3 空格）同样识别；终点是下一个同级/更高级标题行（`#` 或 `##`，
    ≤3 空格缩进）的行首，`###` 及更深层标题属于节内容。
    """
    start = end = None
    offset = 0
    fence = ''
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if fence:
            if stripped == fence[0] * len(stripped) and len(stripped) >= len(fence):
                fence = ''
        elif (run := _FENCE_OPEN.match(stripped)) and (
                run.group(1)[0] == '~' or '`' not in stripped[run.end():]):
            fence = run.group(1)
        elif heading := _atx_heading(line):
            if start is None:
                if heading == (2, _REF_HEADING_TITLE):
                    start = offset
            elif heading[0] <= 2:
                end = offset
                break
        offset += len(line)
    if start is None:
        return None
    return start, len(content) if end is None else end


def _map_outside_fences(content: str, replace) -> str:
    """逐行应用 replace，跳过围栏开合行与围栏内部（围栏规则与
    _ref_section_bounds 一致）：代码示例中的字面 [Pn] 是文本，不是引用。"""
    out = []
    fence = ''
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if fence:
            if stripped == fence[0] * len(stripped) and len(stripped) >= len(fence):
                fence = ''
        elif (run := _FENCE_OPEN.match(stripped)) and (
                run.group(1)[0] == '~' or '`' not in stripped[run.end():]):
            fence = run.group(1)
        else:
            line = replace(line)
        out.append(line)
    return ''.join(out)


def render_styled_markdown(content: str, papers: dict[int, dict], style: str) -> str:
    """Rewrite body `[Pn]` marks per style and rebuild the reference list.

    GB/T 按正文首现顺序编号为 `[n]`；APA 改写为作者—年份文内引用，并与列表
    共用同一套作者—年份—消歧映射。收集与改写范围是文献节之前的正文加上其后的
    tail（附录等后续章节的引用同样参与编号与书目收集，编号在正文之后顺延），
    但不包括代码围栏内部；文献节自身旧条目中的 [Pn] 属于被替换的旧列表，不
    参与。未收录的 `[Pn]` 原样保留、不产生条目。只替换文献节自身的内容范围，
    其后的同级/更高级标题及全部非文献内容（附录、讨论等）逐字保留；「材料
    范围」节的既有拼接行为不变。
    """
    _check_style(style)
    bounds = _ref_section_bounds(content)
    materials = tail = ''
    if bounds is not None:
        start, end = bounds
        body, tail = content[:start], content[end:]
    else:
        body = content
        cut = body.find(MATERIAL_HEADING)
        if cut != -1:
            materials, body = body[cut:], body[:cut]
    keep = lambda line: line
    ordered: list[int] = []
    for pid in first_appearance_ids(_map_outside_fences(body, keep)
                                    + _map_outside_fences(tail, keep)):
        if pid in papers and pid not in ordered:
            ordered.append(pid)
    if style == 'apa':
        marks, lines = _apa_entries(ordered, papers)
        rewrite = {f'[P{pid}]': mark for pid, mark in marks.items()}
    else:
        numbers = {pid: n for n, pid in enumerate(ordered, start=1)}
        rewrite = {f'[P{pid}]': f'[{numbers[pid]}]' for pid in ordered}
        lines = [format_reference(papers[pid], style, index=numbers[pid]) for pid in ordered]

    def _substitute(line: str) -> str:
        for mark, text in rewrite.items():
            line = line.replace(mark, text)
        return line

    body = _map_outside_fences(body, _substitute)
    tail = _map_outside_fences(tail, _substitute)
    if not ordered:
        lines = ['(正文未引用论文)']
    rendered = body.rstrip('\n') + '\n\n## 引用文献\n\n' + '\n'.join(lines)
    if tail:
        rendered += '\n\n' + tail
    if materials:
        rendered += '\n\n' + materials.lstrip('\n')
    return rendered
