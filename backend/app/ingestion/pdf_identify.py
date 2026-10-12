"""Best-effort identity extraction (DOI / arXiv id / title candidate) from a
paper PDF's own text layer and document metadata.

Pure recognition only: no network access, no exceptions escape, and nothing
here changes any import flow. Later cards use these results for dedup and
metadata completion.
"""

from pathlib import Path
import re

import pymupdf as fitz  # PyMuPDF

from app.ingestion.sources import normalize_arxiv_id, normalize_doi

_ALL_NONE = {'doi': None, 'arxiv_id': None, 'title': None}

# Any DOI-shaped token: bare, or behind doi:/DOI:/https://(dx.)doi.org/ — the
# generic ``10.<digits>/<rest>`` shape matches all of those spellings.
_DOI_CANDIDATE_RE = re.compile(r'10\.\d{4,9}/\S+', re.IGNORECASE)
# ``arXiv:<id>``, ``arxiv.org/(abs|pdf)/<id>`` links, and old-style
# ``category/NNNNNNN`` ids (e.g. hep-th/9901001). Bare new-style numbers are
# deliberately not candidates: too many false positives in running text.
_ARXIV_CANDIDATE_RE = re.compile(
    r'(?:arxiv\s*[:=]\s*|arxiv\.org/(?:abs|pdf)/)(\S+)'
    r'|\b([a-z-]+(?:\.[a-z]{2})?/\d{7})\b',
    re.IGNORECASE,
)
# Page provenance markers printed by parse_pdf (or literally present in the
# PDF); they never carry identity information.
_PAGE_MARKER_RE = re.compile(r'<!--\s*page:\s*\d+\s*-->')
# Sentence/bracket punctuation that may glue onto a matched token.
_TRAILING_CHARS = '.,;)]"\''


def _strip_trailing(token: str) -> str:
    return token.rstrip(_TRAILING_CHARS)


def _valid_dois(text: str) -> list[str]:
    """All DOI candidates in ``text`` that pass ``normalize_doi``, in order."""
    valid: list[str] = []
    for match in _DOI_CANDIDATE_RE.finditer(text or ''):
        normalized = normalize_doi(_strip_trailing(match.group(0)))
        if normalized:
            valid.append(normalized)
    return valid


def _first_valid_arxiv(text: str) -> str | None:
    for match in _ARXIV_CANDIDATE_RE.finditer(text or ''):
        candidate = _strip_trailing(match.group(1) or match.group(2) or '')
        if not candidate:
            continue
        try:
            return normalize_arxiv_id(candidate)
        except ValueError:
            continue
    return None


def _meta_title(meta: dict) -> str | None:
    value = meta.get('title')
    if not isinstance(value, str):
        return None
    title = value.strip()
    if not 10 <= len(title) <= 300:
        return None
    if sum(1 for ch in title if ch.isalpha()) * 2 < len(title):
        return None
    if title.lower() == 'untitled':
        return None
    return title


def extract_from_text(text: str, pdf_meta: dict | None = None) -> dict:
    """Extract DOI / arXiv id / title candidate from first-page text.

    Never touches the network and never raises: on any internal failure the
    all-None result is returned instead. The DOI is the *last* valid candidate
    (a paper's own DOI sits in the first-page copyright footer, reference-list
    DOIs appear earlier in extraction order), with DOIs found in
    ``pdf_meta``'s ``subject``/``keywords`` taking priority.
    """
    try:
        meta = pdf_meta if isinstance(pdf_meta, dict) else {}
        meta_dois: list[str] = []
        for field in ('subject', 'keywords'):
            value = meta.get(field)
            if isinstance(value, str) and value:
                meta_dois.extend(_valid_dois(value))
        text_dois = _valid_dois(text)
        return {
            'doi': (meta_dois or text_dois)[-1] if (meta_dois or text_dois) else None,
            'arxiv_id': _first_valid_arxiv(text),
            'title': _meta_title(meta),
        }
    except Exception:
        return dict(_ALL_NONE)


def _open_pdf(pdf_input: bytes | Path):
    """Mirror ``parse_pdf``'s open; frames are cleared so a failed native open
    does not keep the (possibly invalid) file stream referenced on Windows."""
    if isinstance(pdf_input, bytes):
        return fitz.open(stream=pdf_input, filetype="pdf")
    return fitz.open(Path(pdf_input))


def identify_pdf(pdf_input: bytes | Path) -> dict:
    """Identify a PDF from its metadata and the text of its first two pages.

    Encrypted, non-PDF, empty or corrupt inputs yield the all-None dict; this
    function never raises and never touches the network.
    """
    result = dict(_ALL_NONE)
    try:
        document = _open_pdf(pdf_input)
    except Exception as exc:
        import traceback
        pending, seen = [exc], set()
        while pending:
            failed = pending.pop()
            if id(failed) in seen:
                continue
            seen.add(id(failed))
            traceback.clear_frames(failed.__traceback__)
            pending.extend(cause for cause in (failed.__cause__, failed.__context__) if cause is not None)
        return result
    try:
        with document as doc:
            if doc.needs_pass or not doc.is_pdf or doc.page_count == 0:
                return result
            meta = doc.metadata or {}
            page_texts = []
            for page in doc.pages(0, min(2, doc.page_count)):
                page_text = page.get_text("text").strip()
                if page_text:
                    page_texts.append(page_text)
    except Exception:
        return result
    text = _PAGE_MARKER_RE.sub(' ', '\n'.join(page_texts))
    return extract_from_text(text, meta)
