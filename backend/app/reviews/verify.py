"""Deterministic quote and number verification for review fields.

Only the standard library is used: no database, no model calls. Quotes are
matched on a normalized form (NFKC, ligatures, hyphen line breaks, page
markers) with a position map back to the original text, so PDF page locators
keep working. Numbers are canonicalized so 52.70, 1,234 and 1.5×10^-3 compare
equal across value and quote.
"""
import re
import unicodedata
from difflib import SequenceMatcher

_QUOTES = {'\u201c': '"', '\u201d': '"', '\u2018': "'", '\u2019': "'"}
_DASHES = {'\u2013': '-', '\u2014': '-'}
_PAGE_MARKER = re.compile(r'<!--\s*page:\s*\d+\s*-->')
_PAGE_HEADING = re.compile(r'(?m)^[^\S\n]*##\s*第\s*\d+\s*页[^\S\n]*$\n?')
_CITATION = re.compile(r'\[\d{1,3}(?:\s*[,，]\s*\d{1,3})*\]')
_NUMBER = re.compile(r'(?<![\w.])(-?\d+(?:,\d{3})*(?:\.\d+)?)(?:\s*×\s*10\s*\^\s*([+-]?\d+)|e([+-]?\d+))?(?![a-z0-9])')


def _is_ascii_lower(ch):
    return 'a' <= ch <= 'z'


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize text while recording which original index made each output char."""
    pairs = []
    for i, ch in enumerate(text):
        if ch == '\u00ad':
            continue
        for out in unicodedata.normalize('NFKC', ch):
            pairs.append((out, i))
    # Join words the PDF text layer split as 'inver-\nsion' (lowercase only,
    # before dash unification so real en/em dashes at line ends stay visible).
    merged = []
    j = 0
    while j < len(pairs):
        ch, idx = pairs[j]
        if ch == '-' and merged and _is_ascii_lower(merged[-1][0]):
            k = j + 1
            if k < len(pairs) and pairs[k][0] == '\r':
                k += 1
            if k < len(pairs) and pairs[k][0] == '\n' and k + 1 < len(pairs) and _is_ascii_lower(pairs[k + 1][0]):
                j = k + 1
                continue
        merged.append((ch, idx))
        j += 1
    pairs = [(_QUOTES.get(ch) or _DASHES.get(ch) or ch, idx) for ch, idx in merged]
    current = ''.join(ch for ch, _ in pairs)
    drop = [False] * len(pairs)
    for pattern in (_PAGE_MARKER, _PAGE_HEADING):
        for match in pattern.finditer(current):
            for k in range(match.start(), match.end()):
                drop[k] = True
    chars, index = [], []
    pending_space = False
    for (ch, idx), skipped in zip(pairs, drop):
        if skipped:
            continue
        if ch.isspace():
            pending_space = True
            continue
        if pending_space and chars:
            chars.append(' ')
            index.append(idx)
        pending_space = False
        chars.append(ch.lower())
        index.append(idx)
    return ''.join(chars), index


def normalize(text: str) -> str:
    return _normalize_with_map(text)[0]


def _slide(h_norm: str, q_norm: str, threshold: float, lo: int, hi: int):
    """Windowed fuzzy comparison over h_norm[lo:hi]; returns (start, end, ratio) or None."""
    qlen = len(q_norm)
    step = max(1, qlen // 4)
    matcher = SequenceMatcher(None, q_norm, '')
    best = None
    for window in range(max(1, int(qlen * .9)), int(qlen * 1.1) + 1):
        for start in range(lo, max(lo + 1, hi - window + 1), step):
            matcher.set_seq2(h_norm[start:start + window])
            if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
                continue
            ratio = matcher.ratio()
            if ratio >= threshold and (best is None or ratio > best[2]):
                best = (start, start + window, ratio)
    return best


ANCHOR_MIN_LEN = 5
ANCHOR_COUNT = 3
LONG_TEXT = 20000


def _anchor_spans(h_norm: str, q_norm: str) -> list[tuple[int, int]] | None:
    """Searchable regions: one quote length around occurrences of the quote's longest
    words. An empty list means no anchor occurs (no fuzzy hit possible); None means
    no usable anchor word (caller falls back to a full scan)."""
    words = [word for word in q_norm.split() if len(word) >= ANCHOR_MIN_LEN]
    if not words:
        return None
    qlen = len(q_norm)
    spans = []
    for word in sorted(words, key=len, reverse=True)[:ANCHOR_COUNT]:
        pos = h_norm.find(word)
        while pos != -1:
            spans.append((max(0, pos - qlen), min(len(h_norm), pos + len(word) + qlen)))
            pos = h_norm.find(word, pos + 1)
    if not spans:
        return []
    spans.sort()
    merged = [spans[0]]
    for lo, hi in spans[1:]:
        if lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _find_detail(haystack: str, quote: str, threshold: float = 0.9):
    """Positions in the original haystack plus the match similarity, or None."""
    if not quote or not quote.strip():
        return None
    h_norm, h_index = _normalize_with_map(haystack)
    q_norm = normalize(quote)
    if not q_norm:
        return None
    pos = h_norm.find(q_norm)
    if pos >= 0:
        end = pos + len(q_norm)
        return h_index[pos], h_index[end - 1] + 1, 1.0
    if len(q_norm) < 12:
        return None
    if len(h_norm) <= LONG_TEXT:
        best = _slide(h_norm, q_norm, threshold, 0, len(h_norm))
    else:
        spans = _anchor_spans(h_norm, q_norm)
        if spans == []:
            return None  # 锚词一个都不在文中，不可能模糊命中
        regions = spans if spans is not None else [(0, len(h_norm))]
        best = None
        for lo, hi in regions:
            found = _slide(h_norm, q_norm, threshold, lo, hi)
            if found and (best is None or found[2] > best[2]):
                best = found
    if best is None:
        return None
    start, end, ratio = best
    return h_index[start], h_index[end - 1] + 1, ratio


def find_quote(haystack: str, quote: str, threshold: float = 0.9) -> tuple[int, int] | None:
    detail = _find_detail(haystack, quote, threshold)
    return (detail[0], detail[1]) if detail else None


def _canonical_number(mantissa: str, exponent: str | None) -> str:
    mantissa = mantissa.replace(',', '')
    if '.' in mantissa:
        int_part, frac = mantissa.split('.')
        frac = frac.rstrip('0')
        mantissa = f'{int_part}.{frac}' if frac else int_part
    if exponent is not None:
        return f'{mantissa}e{int(exponent.replace(" ", "").lstrip("+"))}'
    return mantissa


def numbers_in(text: str) -> list[str]:
    """Comparable numbers: no separators, no trailing zeros, lowercase exponent.

    Years (1900–2099) and bracketed citation numbers like [12] are excluded.
    """
    cleaned = _CITATION.sub(' ', normalize(text))
    out = []
    for match in _NUMBER.finditer(cleaned):
        mantissa = match.group(1)
        exponent = match.group(2) if match.group(2) is not None else match.group(3)
        token = _canonical_number(mantissa, exponent)
        if exponent is None and token.isdigit() and 1900 <= int(token) <= 2099:
            continue
        out.append(token)
    return out


def check_field(value: str, quote: str, sources: dict[str, str]) -> dict:
    """Verify one field value against its quote across the given sources."""
    result = {'status': 'no_quote', 'found_in': None, 'pages': [], 'missing_numbers': [], 'similarity': None}
    if not quote or not quote.strip():
        return result
    for name, text in sources.items():
        if not text:
            continue
        detail = _find_detail(text, quote)
        if detail is None:
            continue
        start, end, similarity = detail
        result.update(found_in=name, similarity=similarity)
        quote_numbers = set(numbers_in(quote))
        missing = [n for n in numbers_in(value or '') if n not in quote_numbers]
        result['missing_numbers'] = list(dict.fromkeys(missing))
        result['status'] = 'quote_verified' if not missing else 'number_mismatch'
        if name == 'full_text':
            from app.agent.source_passages import text_pages

            result['pages'] = text_pages(text, start, end)
        return result
    result['status'] = 'quote_not_found'
    return result
