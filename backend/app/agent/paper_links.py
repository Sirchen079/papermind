"""Discover original PDF web links independently of the OCR body and index."""
import re
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf

from app.config import get_settings
from app.ingestion.pdf_storage import resolve_pdf


_PRINTED_URL = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
_NOTE = ('Links and nearby selectable PDF text are discovery material. They may be absent from OCR. '
         'No website has been fetched; use read_webpage to check the destination and current availability. '
         'An empty result does not prove that code, models or other resources are unavailable. '
         'Scanned or line-wrapped printed URLs may be missed; consult the original page if needed.')


def _web_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() in {'http', 'https'} and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return None


def _printed_url(value):
    value = value.rstrip('.,;:!?]}>')
    while value.endswith(')') and value.count(')') > value.count('('):
        value = value[:-1]
    return _web_url(value)


def read_paper_links(session, paper_id, page=None, offset=0, limit=20):
    from app.models import Paper
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        return {'error': f'paper {paper_id} not found'}
    base = {'id': paper.id, 'title': paper.title, 'note': _NOTE}
    if page is not None and (not isinstance(page, int) or isinstance(page, bool) or page < 1):
        return {**base, 'error': 'page must be a positive 1-based PDF page'}
    path = resolve_pdf(paper.pdf_path, Path(get_settings().data_dir) / 'pdfs')
    if path is None:
        return {**base, 'error': 'Local PDF is unavailable. Acquire the original PDF to inspect its links.'}
    offset, limit = max(0, int(offset)), max(1, min(40, int(limit)))
    rows = []
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass or not doc.is_pdf or (page is not None and page > doc.page_count):
                return {**base, 'error': 'PDF page is unavailable or the file is encrypted.'}
            indices = [page - 1] if page is not None else range(doc.page_count)
            for index in indices:
                pdf_page = doc[index]
                seen = set()
                for link in pdf_page.get_links():
                    url = _web_url(link.get('uri'))
                    if url is None or url in seen:
                        continue
                    seen.add(url)
                    rect = pymupdf.Rect(link['from'])
                    nearby = pymupdf.Rect(0, max(0, rect.y0 - 14), pdf_page.cropbox.width, rect.y1 + 14)
                    rows.append({'url': url, 'page': index + 1, 'extraction': 'pdf_annotation',
                                 'label': pdf_page.get_textbox(rect).strip()[:240],
                                 'context': pdf_page.get_textbox(nearby).strip()[:600],
                                 'locator': f'PDF 第 {index + 1} 页（原始链接附近文本）'})
                text = pdf_page.get_text('text', sort=True)
                for match in _PRINTED_URL.finditer(text):
                    url = _printed_url(match.group())
                    if url is None or url in seen:
                        continue
                    seen.add(url)
                    rows.append({'url': url, 'page': index + 1, 'extraction': 'printed_url',
                                 'label': url,
                                 'context': text[max(0, match.start() - 200):match.end() + 200].strip()[:600],
                                 'locator': f'PDF 第 {index + 1} 页（印刷网址附近文本）'})
            page_count = doc.page_count
    except Exception as exc:
        return {**base, 'error': 'Could not inspect original PDF links.', 'error_type': type(exc).__name__}
    end = min(offset + limit, len(rows))
    return {**base, 'links': rows[offset:end], 'total_links': len(rows), 'pdf_pages': page_count,
            'offset': offset, 'next_offset': end if end < len(rows) else None,
            **({'requested_page': page} if page is not None else {})}
