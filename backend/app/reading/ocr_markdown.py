"""Normalize document OCR output without changing recognized scientific text."""
import re
from markdownify import markdownify
from bs4 import BeautifulSoup


def _table(match):
    soup = BeautifulSoup(match.group(0), 'html.parser')
    # Markdown has no merged cells. Expand their recognized labels into each
    # covered position before handing conversion to the existing library.
    rows = soup.find_all('tr')
    spans = {}
    def extent(cell, attr):
        value = str(cell.get(attr, '1'))
        return min(100, max(1, int(value))) if value.isdigit() else 1
    width_limit = max((sum(extent(c, 'colspan') for c in r.find_all(['td', 'th'], recursive=False)) for r in rows), default=0)
    for row in rows:
        cells = row.find_all(['td', 'th'], recursive=False)
        # An explicit complete row starts a new group even if OCR's prior
        # rowspan runs one row too long. Never shift those labels and values.
        if sum(extent(c, 'colspan') for c in cells) == width_limit:
            spans.clear()
        col = 0
        expanded = []
        for cell in cells:
            while col in spans:
                value, remaining = spans.pop(col)
                copy = soup.new_tag('td'); copy.string = value
                expanded.append(copy)
                if remaining > 1:
                    spans[col] = (value, remaining - 1)
                col += 1
            value = cell.get_text(' ', strip=True).replace('|', r'\|')
            width = extent(cell, 'colspan')
            height = extent(cell, 'rowspan')
            for _ in range(width):
                copy = soup.new_tag(cell.name); copy.string = value
                expanded.append(copy)
                if height > 1:
                    spans[col] = (value, height - 1)
                col += 1
        while col in spans:
            value, remaining = spans.pop(col)
            copy = soup.new_tag('td'); copy.string = value
            expanded.append(copy)
            if remaining > 1:
                spans[col] = (value, remaining - 1)
            col += 1
        row.clear()
        for cell in expanded:
            row.append(cell)
    return '\n\n' + markdownify(str(soup), table_infer_header=True, escape_underscores=False, escape_asterisks=False).strip() + '\n\n'


def normalize(text):
    text = text.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    # Official grounding format places block labels and coordinates before the
    # recognized content. Remove the annotations, never evaluate coordinates.
    text = re.sub(r'<\|ref\|>[^<>]*<\|/ref\|>\s*<\|det\|>.*?<\|/det\|>', '', text, flags=re.S)
    text = re.sub(r'<table\b[^>]*>.*?</table\s*>', _table, text, flags=re.S | re.I)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    return text.strip()
