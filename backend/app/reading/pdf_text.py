"""Local PDF text assessment and geometric reading order, without OCR.

Coverage is the union of text-line boxes / the visible content envelope,
including images and vector drawings. It is a routing heuristic, not OCR accuracy.
Uses the existing PyMuPDF extraction and ruled-table APIs; no new runtime.
"""
import re
import unicodedata

import pymupdf

MIN_TEXT_COVERAGE = .05
MAX_GARBLE_RATE = .01


def _union_area(boxes):
    edges = sorted({v for b in boxes for v in (b.x0, b.x1)})
    area = 0.
    for left, right in zip(edges, edges[1:]):
        intervals = sorted((b.y0, b.y1) for b in boxes if b.x0 < right and b.x1 > left)
        end, height = float('-inf'), 0.
        for low, high in intervals:
            height += max(0., high - max(low, end))
            end = max(end, high)
        area += (right - left) * height
    return area


def text_quality(text, text_boxes, content_boxes):
    envelope = pymupdf.Rect()
    for box in content_boxes:
        envelope |= box
    coverage = min(1., _union_area(text_boxes) / max(1., envelope.get_area()))
    chars = ''.join(text.split())
    broken = sum(c == '\ufffd' or unicodedata.category(c) in {'Cc', 'Cs', 'Co', 'Cn'} for c in chars)
    broken += sum(len(m.group()) for m in re.finditer(r'\(cid:\d+\)', chars))
    garble = min(1., broken / max(1, len(chars)))
    reasons = ([] if chars else ['no_text']) + ([] if coverage >= MIN_TEXT_COVERAGE else ['low_coverage'])
    if garble > MAX_GARBLE_RATE:
        reasons.append('garbled')
    return {'coverage': coverage, 'garble_rate': garble, 'reliable': not reasons, 'reasons': reasons,
            'min_coverage': MIN_TEXT_COVERAGE, 'max_garble_rate': MAX_GARBLE_RATE}


def _gap(items, axis):
    intervals = sorted((item[0][axis], item[0][axis + 2]) for item in items)
    end = intervals[0][1]
    gaps = []
    for low, high in intervals[1:]:
        if low > end:
            gaps.append((low - end, (low + end) / 2))
        end = max(end, high)
    return max(gaps, default=(0, 0))


def _reading_order(items, depth=0):
    if len(items) < 2 or depth > 32:
        return sorted(items, key=lambda item: (item[0].y0, item[0].x0))
    # A vertical gutter takes precedence, so aligned paragraphs do not interleave
    # across columns. Horizontal whitespace separates spanning titles/captions.
    width, split = _gap(items, 0)
    axis = 0
    if width < 12:
        width, split = _gap(items, 1)
        axis = 1
        if width < 5:
            return sorted(items, key=lambda item: (item[0].y0, item[0].x0))
    first = [item for item in items if item[0][axis] < split]
    second = [item for item in items if item[0][axis] >= split]
    return _reading_order(first, depth + 1) + _reading_order(second, depth + 1)


def native_page(page):
    visible = page.rect * page.derotation_matrix
    blocks = page.get_text('dict', flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']
    items = []
    for block_id, block in enumerate(blocks):
        for line in block.get('lines', []):
            text = ''.join(span['text'] for span in line['spans']).strip()
            box = pymupdf.Rect(line['bbox']) & visible
            if text and not box.is_empty:
                items.append((box, text, block_id))
    text_boxes = [item[0] for item in items]
    images = [pymupdf.Rect(info['bbox']) & visible for info in page.get_image_info()]
    paths = page.get_drawings()
    # Ignore a white page background when estimating the content envelope.
    drawings = [pymupdf.Rect(path['rect']) & visible for path in paths
                if path.get('fill') != (1., 1., 1.)]
    content = [box for box in text_boxes + images + drawings if not box.is_empty]
    raw_text = '\n'.join(item[1] for item in items)
    quality = text_quality(raw_text, text_boxes, content)
    if not raw_text and not images and not paths:
        return '[空白页]', {**quality, 'reliable': True, 'reasons': ['blank']}
    if not quality['reliable']:
        return raw_text, quality
    # Preserve ruled tables as one layout region rather than treating their cells
    # as newspaper columns. All values come from the PDF's own text layer.
    if len(paths) >= 4 and items:
        tables = []
        try:
            tables = [(pymupdf.Rect(table.bbox), table.to_markdown())
                      for table in page.find_tables(strategy='lines_strict').tables]
        except Exception:
            # Optional table reconstruction must not discard readable text.
            quality['layout_fallback'] = 'table_detection_failed'
        for table_id, (box, table_text) in enumerate(tables):
            if table_text:
                items = [item for item in items if not box.contains(item[0])]
                items.append((box, table_text, ('table', table_id)))
    chunks, previous = [], None
    for _, text, block_id in _reading_order(items):
        if chunks and previous == block_id:
            chunks[-1] += '\n' + text
        else:
            chunks.append(text)
        previous = block_id
    return '\n\n'.join(chunks), quality
