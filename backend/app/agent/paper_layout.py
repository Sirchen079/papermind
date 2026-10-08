"""Read a local PDF page in physical layout order, without rewriting its index."""
from pathlib import Path

import pymupdf

from app.config import get_settings
from app.ingestion.pdf_storage import resolve_pdf


def read_layout_page(paper, page, start_char=0, max_chars=6000):
    base = {'id': paper.id, 'title': paper.title, 'layout': True}
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        return {**base, 'note': 'Layout reading requires a positive 1-based PDF page.'}
    path = resolve_pdf(paper.pdf_path, Path(get_settings().data_dir) / 'pdfs')
    if path is None:
        return {**base, 'note': 'Local PDF is unavailable. Omit layout to read stored text, or acquire the full text.'}
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass or not doc.is_pdf or page > doc.page_count:
                return {**base, 'note': 'PDF page is unavailable or encrypted. Omit layout to read stored text.'}
            # PyMuPDF reconstructs lines from their positions. Do not invent
            # cells or propagate merged headers across rows.
            text = doc[page - 1].get_text('text', sort=True).strip()
    except Exception as exc:
        return {**base, 'note': 'Could not read the local PDF page. Omit layout to read stored text.',
                'error_type': type(exc).__name__}
    if not text:
        return {**base, 'note': 'This PDF page has no selectable text. Use the existing OCR/Markdown workflow; an empty extraction does not establish that the page has no evidence.'}
    text = text.replace('<!-- page:', '&lt;!-- page:')
    start = max(0, min(int(start_char), len(text)))
    end = min(len(text), start + max(500, min(int(max_chars), 12000)))
    return {**base, 'text': text[start:end], 'pages': [page],
            'locator': f'PDF 第 {page} 页（版面文本）',
            'start_char': start, 'end_char': end, 'total_chars': len(text),
            'truncated': start > 0 or end < len(text),
            'next_start_char': end if end < len(text) else None,
            'note': 'Text reconstructed from PDF positions, not verified table cells. Preserve headers, units, group labels and captions. Merged headers and multiple columns may remain ambiguous; compare with ordinary section text or the original PDF. Offsets refer to this layout page only; keep layout=true and the same page when continuing.'}
