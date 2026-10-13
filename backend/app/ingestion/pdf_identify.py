"""Best-effort identity extraction (DOI / arXiv id / title candidate) from a
paper PDF's own text layer and document metadata.

Pure recognition only: no network access, no exceptions escape, and nothing
here changes any import flow. Later cards use these results for dedup and
metadata completion.
"""

from pathlib import Path
import re

import pymupdf as fitz  # PyMuPDF

from app.ingestion.dedup import normalize_title
from app.ingestion.sources import normalize_arxiv_id, normalize_doi

_ALL_NONE = {'doi': None, 'arxiv_id': None, 'title': None}
_ALL_NONE_CANDIDATES = {
    'title': None, 'text': '',
    'doi': None, 'doi_kind': None, 'doi_candidates': [],
    'arxiv_id': None, 'arxiv_kind': None, 'arxiv_candidates': [],
}

# Any DOI-shaped token: bare, or behind doi:/DOI:/https://(dx.)doi.org/ — the
# generic ``10.<digits>/<rest>`` shape matches all of those spellings.
_DOI_CANDIDATE_RE = re.compile(r'10\.\d{4,9}/\S+', re.IGNORECASE)
# The explicitly self-declared spellings (``doi:…``, a resolver URL). Reference
# lists most often print bare DOIs, so labeled candidates are stronger evidence
# of the document's own identity.
_LABELED_DOI_RE = re.compile(
    r'(?:\bdoi\s*[:=]\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/\S+)',
    re.IGNORECASE,
)
# ``arXiv:<id>``, ``arxiv.org/(abs|pdf)/<id>`` links, and old-style
# ``category/NNNNNNN`` ids (e.g. hep-th/9901001). Bare new-style numbers are
# deliberately not candidates: too many false positives in running text.
_ARXIV_CANDIDATE_RE = re.compile(
    r'(?:arxiv\s*[:=]\s*|arxiv\.org/(?:abs|pdf)/)(\S+)'
    r'|\b([a-z-]+(?:\.[a-z]{2})?/\d{7})\b',
    re.IGNORECASE,
)
# A standalone heading that starts the reference list; DOIs/arXiv ids after it
# belong to cited works, not to the uploaded document itself.
_REFERENCES_HEADING_RE = re.compile(
    r'^\s*(?:references|bibliography|works?\s+cited|literature\s+cited|'
    r'参考文献|參考文獻|文献)\s*[:：]?\s*$',
    re.IGNORECASE | re.MULTILINE,
)
# Candidate provenance, strongest first: publisher metadata > document body >
# reference list. Identity usable for auto-merge is decided from this later
# (see verify_upload_identity); extraction only reports what it saw.
_CANDIDATE_KINDS = ('metadata', 'body', 'reference')
# Page provenance markers printed by parse_pdf (or literally present in the
# PDF); they never carry identity information.
_PAGE_MARKER_RE = re.compile(r'<!--\s*page:\s*\d+\s*-->')
# Sentence/bracket punctuation that may glue onto a matched token.
_TRAILING_CHARS = '.,;)]"\''


def _strip_trailing(token: str) -> str:
    return token.rstrip(_TRAILING_CHARS)


def _meta_doi_candidates(value: str) -> list[dict]:
    return _doi_candidates_with_kind(value, 'metadata', None)


def _doi_candidates_with_kind(text: str, kind: str, reference_start: int | None) -> list[dict]:
    """DOI candidates in reading order; ``reference_start`` splits off the
    reference list, where identifiers belong to cited works."""
    found: list[dict] = []
    labeled_spans = []
    for match in _LABELED_DOI_RE.finditer(text or ''):
        labeled_spans.append(match.span(1))
        found.append({'start': match.start(1), 'raw': match.group(1), 'labeled': True})
    for match in _DOI_CANDIDATE_RE.finditer(text or ''):
        if any(ls < match.end() and match.start() < le for ls, le in labeled_spans):
            continue
        found.append({'start': match.start(), 'raw': match.group(0), 'labeled': False})
    out: list[dict] = []
    for item in found:
        normalized = normalize_doi(_strip_trailing(item['raw']))
        if not normalized:
            continue
        out.append({'doi': normalized, 'labeled': item['labeled'],
                    'kind': 'reference' if kind == 'body' and reference_start is not None
                    and item['start'] >= reference_start else kind})
    return out


def _arxiv_candidates(text: str, reference_start: int | None) -> list[dict]:
    out: list[dict] = []
    for match in _ARXIV_CANDIDATE_RE.finditer(text or ''):
        raw = _strip_trailing(match.group(1) or match.group(2) or '')
        if not raw:
            continue
        try:
            normalized = normalize_arxiv_id(raw)
        except ValueError:
            continue
        out.append({'arxiv_id': normalized, 'labeled': match.group(1) is not None,
                    'kind': 'reference' if reference_start is not None
                    and match.start() >= reference_start else 'body'})
    return out


def _select_candidate(candidates: list[dict], key: str):
    """Best candidate by provenance (metadata > body > reference; labeled beats
    bare; last occurrence wins within a group — the self DOI sits in the
    first-page footer). Selection stays a *candidate*: verification decides
    whether it may auto-merge."""
    for kind in _CANDIDATE_KINDS:
        group = [c for c in candidates if c['kind'] == kind]
        if group:
            labeled = [c for c in group if c.get('labeled')]
            return (labeled or group)[-1][key], kind
    return None, None


def extract_candidates(text: str, pdf_meta: dict | None = None) -> dict:
    """All identity candidates in the text with their provenance, plus the
    document text used.

    Never touches the network and never raises. ``doi``/``arxiv_id`` are the
    best *candidates* only — a hit on them proves a record exists, not that it
    matches this upload; ``*_kind``/``*_candidates`` keep the source
    information (metadata/body/reference) so callers can tell a self-declared
    identifier from a citation seen in the references.
    """
    try:
        meta = pdf_meta if isinstance(pdf_meta, dict) else {}
        heading = _REFERENCES_HEADING_RE.search(text or '')
        reference_start = heading.start() if heading else None
        doi_candidates: list[dict] = []
        for field in ('subject', 'keywords'):
            value = meta.get(field)
            if isinstance(value, str) and value:
                doi_candidates.extend(_meta_doi_candidates(value))
        doi_candidates.extend(_doi_candidates_with_kind(text, 'body', reference_start))
        arxiv_candidates = _arxiv_candidates(text, reference_start)
        doi, doi_kind = _select_candidate(doi_candidates, 'doi')
        arxiv_id, arxiv_kind = _select_candidate(arxiv_candidates, 'arxiv_id')
        return {
            'title': _meta_title(meta),
            'text': text or '',
            'doi': doi, 'doi_kind': doi_kind, 'doi_candidates': doi_candidates,
            'arxiv_id': arxiv_id, 'arxiv_kind': arxiv_kind,
            'arxiv_candidates': arxiv_candidates,
        }
    except Exception:
        return dict(_ALL_NONE_CANDIDATES)


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
    all-None result is returned instead. Selection prefers the document's own
    metadata, then body candidates (labeled self-declarations over bare DOIs,
    last occurrence — the footer), and only falls back to reference-list
    candidates; see :func:`extract_candidates` for the full provenance.
    """
    try:
        full = extract_candidates(text, pdf_meta)
    except Exception:
        return dict(_ALL_NONE)
    return {key: full.get(key) for key in _ALL_NONE}


def _open_pdf(pdf_input: bytes | Path):
    """Mirror ``parse_pdf``'s open; frames are cleared so a failed native open
    does not keep the (possibly invalid) file stream referenced on Windows."""
    if isinstance(pdf_input, bytes):
        return fitz.open(stream=pdf_input, filetype="pdf")
    return fitz.open(Path(pdf_input))


def _identify_pdf_full(pdf_input: bytes | Path) -> dict:
    """Like :func:`identify_pdf`, but also returns the extracted text and the
    full candidate lists for verification decisions."""
    result = dict(_ALL_NONE_CANDIDATES)
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
    return extract_candidates(text, meta)


def identify_pdf(pdf_input: bytes | Path) -> dict:
    """Identify a PDF from its metadata and the text of its first two pages.

    Encrypted, non-PDF, empty or corrupt inputs yield the all-None dict; this
    function never raises and never touches the network.
    """
    full = _identify_pdf_full(pdf_input)
    return {key: full.get(key) for key in _ALL_NONE}


def _merge_conflict(candidate: dict, verified) -> str | None:
    """``None`` when the retrieved metadata may auto-merge, else a reason code.

    A lookup hit only proves the record exists, not that it matches this
    upload. Merging additionally requires the retrieved identity to be
    consistent with what the document itself declares: its own metadata title,
    or — when several distinct candidates were seen or only a reference-list
    candidate exists — the retrieved title appearing in the document text.
    """
    verified_title = (verified.title or '').strip()
    pdf_title = (candidate.get('title') or '').strip()
    if pdf_title and verified_title and \
            normalize_title(pdf_title) != normalize_title(verified_title):
        return 'title_conflict'
    candidates = candidate.get('doi_candidates', []) + candidate.get('arxiv_candidates', [])
    values = {c.get('doi') or c.get('arxiv_id') for c in candidates}
    selected = candidate.get('doi') or candidate.get('arxiv_id')
    selected_kind = (candidate.get('doi_kind') if candidate.get('doi')
                     else candidate.get('arxiv_kind'))
    ambiguous = len(values) > 1
    if selected and verified_title and (ambiguous or selected_kind == 'reference'):
        text_norm = normalize_title(candidate.get('text') or '')
        if text_norm and normalize_title(verified_title) not in text_norm:
            return 'unverified_title'
    return None


def _candidate_provenance(candidate: dict) -> list[dict]:
    provenance = [c for c in candidate.get('doi_candidates', [])]
    provenance.extend(candidate.get('arxiv_candidates', []))
    return [{**c} for c in provenance]


def verify_upload_identity(data: bytes, filename: str | None) -> tuple[dict, dict]:
    """Verify an uploaded PDF's identity against arXiv/Crossref (best effort).

    Network access is allowed here, but no exception ever escapes: an outage
    only degrades the receipt. Returns ``(fields, receipt)`` where ``fields``
    prefers verified bibliographic values and falls back to what the PDF itself
    declares (``title`` only from verification or the document's metadata —
    ``filename`` is never used as a title), and ``receipt`` records whether
    verification came from arxiv/crossref/none and its status.

    Verified values are applied only when they are consistent with the
    document (see :func:`_merge_conflict`). On conflict or reference-only
    evidence the receipt degrades to ``unconfirmed`` with the contested
    identifiers withheld, so an independent entry is saved instead of merging
    into whichever record the lookup happened to hit.
    """
    candidate = _identify_pdf_full(data)
    fields = {'title': candidate.get('title'), 'authors': [], 'abstract': None,
              'year': None, 'venue': None, 'volume': None, 'issue': None,
              'pages': None, 'doi': candidate.get('doi'),
              'arxiv_id': candidate.get('arxiv_id')}
    receipt: dict = {'status': 'none', 'source': 'none'}
    try:
        verified = None
        if fields['arxiv_id']:
            from app.ingestion.sources import fetch_arxiv_metadata
            verified, receipt = fetch_arxiv_metadata(fields['arxiv_id'])
        if verified is None and fields['doi']:
            from app.ingestion.sources import lookup_doi_metadata
            verified, receipt = lookup_doi_metadata(fields['doi'])
        if verified is not None:
            conflict = _merge_conflict(candidate, verified)
            if conflict is not None:
                # The record the lookup hit is not provably this document:
                # keep the PDF's own values, withhold the contested identifiers
                # from dedup, and leave the merge to the user.
                fields['doi'] = None
                fields['arxiv_id'] = None
                receipt = {'status': 'unconfirmed', 'source': receipt.get('source') or 'none',
                           'identifier': receipt.get('identifier'), 'reason': conflict,
                           'candidates': _candidate_provenance(candidate)}
            else:
                fields['title'] = verified.title or fields['title']
                if verified.authors:
                    fields['authors'] = [str(author) for author in verified.authors]
                for field in ('abstract', 'year', 'venue', 'volume', 'issue', 'pages',
                              'doi', 'arxiv_id'):
                    value = getattr(verified, field)
                    if value:
                        fields[field] = value
    except Exception as exc:  # noqa: BLE001 — verification must never block an upload
        receipt = {**receipt, 'status': 'unavailable', 'error_type': type(exc).__name__}
    return fields, receipt
