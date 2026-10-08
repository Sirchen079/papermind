"""Preserve the actual passages read by the agent and their PDF locations."""
import re

PAGE_MARKER = re.compile(r'<!-- page:(\d+) -->')
INDEX_PAGE = re.compile(r'^\[第 (\d+) 页\]', re.MULTILINE)


def valid_pages(values):
    return list(dict.fromkeys(p for p in values if isinstance(p, int) and not isinstance(p, bool) and p > 0))


def text_pages(text, start, end):
    """A slice may start mid-page; use stored extraction markers, not prose numbers."""
    markers = list(PAGE_MARKER.finditer(text))
    pages = []
    for index, marker in enumerate(markers):
        stop = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        left, right = max(start, marker.end()), min(end, stop)
        if left < right and text[left:right].strip():
            pages.append(int(marker[1]))
    return valid_pages(pages)


def indexed_pages(text):
    return valid_pages(int(match[1]) for match in INDEX_PAGE.finditer(text))


def paper_source(paper_id, title, text, source_type, retrieved_by, pages=(), locator=None):
    text = text if isinstance(text, str) else ''
    pages = valid_pages(pages)
    source = {'paper_id': paper_id, 'title': title or f'#{paper_id}',
              'snippet': ' '.join(text.split())[:280], 'excerpt': text[:12000],
              'excerpt_truncated': len(text) > 12000,
              'source_type': source_type, 'retrieved_by': retrieved_by, 'pages': pages}
    if locator:
        source['locator'] = locator
    elif pages:
        source['locator'] = 'PDF 第 ' + '、'.join(map(str, pages)) + ' 页'
    return source
