"""Readable views of scholarly API records, without treating metadata as full text."""
from html import unescape
from html.parser import HTMLParser
import json
from urllib.parse import urlsplit


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {'p', 'jats:p', 'title', 'jats:title', 'section', 'jats:sec'}:
            self.parts.append('\n')


def _text(value):
    if isinstance(value, list):
        return '; '.join(_text(v) for v in value)
    if not isinstance(value, str):
        return ''
    parser = _Text()
    parser.feed(value)
    return unescape(''.join(parser.parts)).strip()


def _abstract(index):
    if not isinstance(index, dict):
        return ''
    words = {}
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and not isinstance(position, bool) and position >= 0:
                words[position] = word
    # Sort sparse positions; never allocate a list using an external maximum index.
    return ' '.join(words[k] for k in sorted(words))


def scholarly_view(url, raw):
    """Return text/links for recognized work responses, or None for raw fallback.

    This view is intentionally scoped to API work endpoints. Unrecognized JSON,
    including other endpoints on these hosts, stays available unchanged.
    """
    parsed = urlsplit(url)
    if parsed.hostname not in {'api.openalex.org', 'api.crossref.org'} or not (
        parsed.path == '/works' or parsed.path.startswith('/works/')
    ):
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    openalex = parsed.hostname == 'api.openalex.org'
    if openalex:
        rows = data.get('results') if isinstance(data.get('results'), list) else [data]
    else:
        message = data.get('message')
        if not isinstance(message, dict):
            return None
        rows = message.get('items') if isinstance(message.get('items'), list) else [message]
    if not rows or not all(isinstance(r, dict) and (r.get('title') or r.get('display_name')) for r in rows):
        return None
    parts = ['Scholarly metadata and abstracts (not article full text).',
             'API response: ' + url,
             'Records in this response: ' + str(len(rows))]
    links, seen = [], set()

    def link(target, title):
        if isinstance(target, str) and urlsplit(target).scheme in {'https', 'http'} and target not in seen:
            seen.add(target)
            links.append({'url': target, 'title': title})
            return target
        return ''

    for i, row in enumerate(rows, 1):
        title = _text(row.get('title') or row.get('display_name'))
        doi = row.get('doi') if openalex else row.get('DOI')
        doi_url = doi if isinstance(doi, str) and doi.startswith('https://doi.org/') else ('https://doi.org/' + doi if isinstance(doi, str) else '')
        parts.extend(['', f'Record {i}: {title}', 'DOI: ' + (doi_url or 'not provided')])
        abstract = _abstract(row.get('abstract_inverted_index')) if openalex else _text(row.get('abstract'))
        parts.append('Abstract: ' + (abstract or 'Not provided by this API record.'))
        if openalex:
            authors = [a.get('author', {}).get('display_name', '') for a in row.get('authorships', []) if isinstance(a, dict) and isinstance(a.get('author'), dict)]
            dates = {k: row[k] for k in ('publication_year', 'publication_date') if row.get(k)}
            locations = [row.get('best_oa_location'), row.get('primary_location'), *(row.get('locations') or [])]
            venue = ((row.get('primary_location') or {}).get('source') or {}).get('display_name', '')
        else:
            authors = [' '.join(filter(None, [a.get('given'), a.get('family')])) or a.get('name', '') for a in row.get('author', []) if isinstance(a, dict)]
            dates = {k: row[k].get('date-parts') for k in ('published-print', 'published-online', 'published', 'issued') if isinstance(row.get(k), dict)}
            locations = []
            venue = _text(row.get('container-title'))
        parts.extend(['Authors: ' + '; '.join(authors[:10]) + (f' (+{len(authors)-10}; raw_json=true for all)' if len(authors) > 10 else ''),
                      'Dates: ' + json.dumps(dates, ensure_ascii=False), 'Venue: ' + venue])
        for field in ('volume', 'issue', 'page', 'article-number'):
            if row.get(field):
                parts.append(field + ': ' + str(row[field]))
        # These URLs are discovered entry points, not evidence that a PDF was read
        # or that a publisher has granted access. Do not invent a download URL.
        record_links = []
        for loc in locations:
            if isinstance(loc, dict):
                for field in ('pdf_url', 'landing_page_url'):
                    target = link(loc.get(field), title + ' — ' + field)
                    if target:
                        record_links.append(target)
        for item in row.get('link', []) if not openalex else []:
            if isinstance(item, dict):
                target = link(item.get('URL'), title + ' — publisher resource')
                if target:
                    record_links.append(target)
        target = link(doi_url, title)
        if target:
            record_links.append(target)
        parts.append('Article entry points (not yet read): ' + ('; '.join(record_links) or 'none provided'))
    return '\n'.join(parts), links
