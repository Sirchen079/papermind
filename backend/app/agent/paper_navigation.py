"""Locate original text without assuming a PDF's first mention is its answer."""
import re
from bisect import bisect_right

from app.agent.source_passages import PAGE_MARKER, text_pages


def paper_sections(text):
    """Best-effort headings from extracted text; offsets always refer to the original.

    PDF extraction often puts a section number on its own line. Only accept
    ordered numbered headings and short heading-like titles, so table cells and
    printed page numbers do not normally become navigation entries.
    """
    lines = list(re.finditer(r'[^\r\n]+', text))
    sections = []
    last_main = 0
    active_root = None
    seen = set()
    consumed = set()
    appendix_allowed = False
    has_pdf_pages = bool(PAGE_MARKER.search(text))
    named = {'abstract', 'references', 'bibliography', 'limitations',
             'acknowledgments', 'acknowledgements', 'ethics statement',
             'introduction', 'methods', 'methodology', 'results', 'discussion',
             'conclusion', 'conclusions', 'appendix', '摘要', '参考文献',
             '引言', '方法', '结果', '讨论', '结论', '附录'}
    number_pattern = r'(\d{1,2}(?:\.\d{1,2}){0,3}|[A-Z](?:\.\d{1,2}){0,3})'
    for index, line in enumerate(lines):
        if index in consumed:
            continue
        raw = line.group().strip()
        if re.match(r'^#{1,6}\s+第\s*\d+\s*页\s*$', raw):
            continue
        markdown = re.match(r'^(#{1,6})\s+(.+?)(?:\s+#+)?$', raw)
        if (markdown and has_pdf_pages and index + 1 < len(lines)
                and re.fullmatch(r'[\d\s,.%+\-]+', lines[index + 1].group())):
            # PDF table headers such as '# Instance' followed by a count are
            # not document sections, including in OCR's Markdown output.
            continue
        value = markdown[2] if markdown else raw
        number, title = '', value
        match = re.match(r'^' + number_pattern + r'\.?\s+(.+)$', value)
        title_end = line.end()
        split_number = False
        if match:
            number, title = match[1], match[2]
        elif re.fullmatch(number_pattern + r'\.?', value) and index + 1 < len(lines):
            number = value.rstrip('.')
            title = lines[index + 1].group().strip()
            title_end = lines[index + 1].end()
            split_number = True
        elif not markdown and value.casefold() not in named:
            continue
        if (not title or len(title) > 100 or len(title.split()) > 14 or
                not title[0].isalpha() or title.endswith(('.', ',', ';', ':', '?', '!')) or
                '<!--' in title or (title[0].isascii() and not title[0].isupper())):
            continue
        if len(title.split()) == 1 and any(ch.isdigit() for ch in title):
            continue
        level = len(number.split('.')) if number else (len(markdown[1]) if markdown else 1)
        if number:
            root = number.split('.')[0]
            if number in seen:
                previous = next(row for row in sections if row['number'] == number)
                first_line = text[previous['start_char']:previous['heading_end_char']].splitlines()[0]
                # A prose list such as "3. Lack of datasets" can precede the
                # actual PDF heading "3\nSystem Description". Prefer that
                # standalone heading before any of its subsections were read.
                if (split_number and level == 1 and active_root == root and
                        first_line.startswith(number + '. ') and
                        not any(row['number'].startswith(number + '.') for row in sections)):
                    sections.remove(previous)
                    seen.remove(number)
                    if root.isdigit():
                        last_main -= 1
                else:
                    continue
            if level == 1 and root.isdigit():
                if int(root) != last_main + 1 and not markdown:
                    continue
                last_main = int(root)
                active_root = root
            elif level == 1:
                if not appendix_allowed or (root != 'A' and (active_root is None or not active_root.isalpha() or
                                     ord(root) != ord(active_root) + 1)):
                    continue
                active_root = root
            elif root != active_root and not markdown:
                continue
            seen.add(number)
        if title.casefold() in {'references', 'bibliography', 'conclusion', 'conclusions', 'appendix',
                               '参考文献', '结论', '附录'}:
            appendix_allowed = True
        if split_number:
            consumed.add(index + 1)
        sections.append({'number': number, 'title': title, 'level': level,
                         'start_char': line.start(), 'heading_end_char': title_end})
    if any(row['number'] for row in sections):
        # In numbered PDFs, standalone "Methods"/"Results" are often table
        # headers or wrapped heading tails, not new top-level sections.
        trailing = {'abstract', 'references', 'bibliography', 'limitations', 'ethics statement',
                    'acknowledgments', 'acknowledgements', '摘要', '参考文献'}
        sections = [row for row in sections if row['number'] or row['title'].casefold() in trailing
                    or text[row['start_char']:].startswith('#')]
    for index, section in enumerate(sections):
        section['end_char'] = next((later['start_char'] for later in sections[index + 1:]
                                    if later['level'] <= section['level']), len(text))
        section['pages'] = text_pages(text, section['start_char'], section['heading_end_char'])
    return sections


def section_outline(sections):
    return [{key: row[key] for key in ('number', 'title', 'start_char', 'pages')}
            for row in sections[:80]]


def find_sections(sections, requested):
    key = requested.strip().casefold()
    if not key:
        return []
    exact = [row for row in sections if key in {row['number'].casefold(), row['title'].casefold(),
                                              (row['number'] + ' ' + row['title']).strip().casefold()}]
    return exact or [row for row in sections if key in row['title'].casefold()]


def page_bounds(text, page):
    markers = list(PAGE_MARKER.finditer(text))
    for index, marker in enumerate(markers):
        if int(marker[1]) == page:
            stop = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            return marker.start(), stop
    return None


def phrase_matches(text, query, start, end):
    # PDF line breaks between words should not hide an otherwise exact phrase.
    # Match against the original string to preserve source offsets.
    pattern = r'\s+'.join(re.escape(word) for word in query.split())
    return list(re.finditer(pattern, text[start:end], re.IGNORECASE)) if pattern else []


def match_navigation(text, matches, search_start, search_end, excerpt_start, excerpt_end):
    """Show representative other locations, with verbatim, sourceable previews."""
    positions = [search_start + match.start() for match in matches]
    later = [pos for pos in positions if pos >= excerpt_end]
    candidates = []
    seen = set()
    markers = list(PAGE_MARKER.finditer(text))
    page_starts = [marker.end() for marker in markers]
    for pos in positions:
        if excerpt_start <= pos < excerpt_end:
            continue
        page_index = bisect_right(page_starts, pos) - 1
        # One preview per PDF page, or per region for imports without markers.
        key = ('page', page_index) if page_index >= 0 else ('offset', pos // 1500)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(pos)
    if len(candidates) > 8:
        # Include late implementation appendices as well as early locations.
        candidates = [candidates[round(i * (len(candidates) - 1) / 7)] for i in range(8)]
    previews = []
    for pos in candidates:
        left, right = max(search_start, pos - 80), min(search_end, pos + 220)
        previews.append({'match_char': pos, 'start_char': left, 'end_char': right,
                         'pages': text_pages(text, left, right), 'text': text[left:right]})
    return {'match_count': len(matches), 'other_matches': previews,
            'next_match_start_char': later[0] if later else None}
