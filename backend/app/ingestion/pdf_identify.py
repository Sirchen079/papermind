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
# How many leading non-empty lines may jointly form the document's own title
# when no metadata title exists; matching never starts later than the first
# non-empty content line.
_TITLE_MAX_LINES = 4
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


def _self_declared_text(text: str) -> str:
    """The region where a title can count as this document's own statement:
    everything before the reference-list heading. A title seen inside the
    reference list belongs to a cited work and never proves this upload's
    identity (W01/F01)."""
    heading = _REFERENCES_HEADING_RE.search(text or '')
    return text[:heading.start()] if heading else (text or '')


def _title_area_match(text: str, verified_norm: str) -> bool:
    """True when the verified title is the document's own leading title block:
    the first non-empty line of the pre-reference text, optionally joined with
    the following lines up to :data:`_TITLE_MAX_LINES`, normalizes exactly to
    it. Anything else — a title deeper in the page, or in unrecognized layouts
    — returns False and degrades to 'unverified_title', never to a merge.
    """
    if not verified_norm:
        return False
    lines: list[str] = []
    for raw in _self_declared_text(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
        if len(lines) >= _TITLE_MAX_LINES:
            break
    joined = ''
    for line in lines:
        joined = normalize_title(f'{joined} {line}')
        if joined == verified_norm:
            return True
        if len(joined) > len(verified_norm):
            break
    return False


def _merge_conflict(candidate: dict, verified,
                    queried_kind: str | None = None) -> str | None:
    """``None`` when the retrieved metadata may auto-merge, else a reason code.

    The gate is driven by the provenance of the identifier actually queried:
    a ``metadata``-kind candidate (the PDF's own metadata) is self-declared
    and needs no further evidence; a body/reference candidate additionally
    needs the document's own metadata title to equal the retrieved title, or
    the retrieved title to be the leading title block of the first page. A
    title merely mentioned in the body, or printed only in the reference
    list, is a citation — not this document's name.
    """
    verified_title = (verified.title or '').strip()
    pdf_title = (candidate.get('title') or '').strip()
    if pdf_title and verified_title and \
            normalize_title(pdf_title) != normalize_title(verified_title):
        return 'title_conflict'
    if queried_kind != 'metadata':
        verified_norm = normalize_title(verified_title)
        pdf_match = bool(pdf_title and verified_title
                         and normalize_title(pdf_title) == verified_norm)
        if not pdf_match and not _title_area_match(candidate.get('text') or '',
                                                   verified_norm):
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
    document (see :func:`_merge_conflict`). Whenever the lookup fails to
    confirm the document — conflict, reference-only evidence, outage, or an
    escaping error — the candidate identifiers are withheld from ``fields``
    (W01/F02: they must never drive dedup) and the receipt degrades to
    ``unconfirmed``/``unavailable``, so an independent entry is saved instead
    of merging into whichever record the lookup happened to hit.
    """
    candidate = _identify_pdf_full(data)
    fields = {'title': candidate.get('title'), 'authors': [], 'abstract': None,
              'year': None, 'venue': None, 'volume': None, 'issue': None,
              'pages': None, 'doi': candidate.get('doi'),
              'arxiv_id': candidate.get('arxiv_id')}
    receipt: dict = {'status': 'none', 'source': 'none'}
    confirmed = False
    try:
        verified = None
        queried_kind = None
        if fields['arxiv_id']:
            from app.ingestion.sources import fetch_arxiv_metadata
            verified, receipt = fetch_arxiv_metadata(fields['arxiv_id'])
            queried_kind = candidate.get('arxiv_kind')
        if verified is None and fields['doi']:
            from app.ingestion.sources import lookup_doi_metadata
            verified, receipt = lookup_doi_metadata(fields['doi'])
            if verified is not None:
                queried_kind = candidate.get('doi_kind')
        if verified is not None:
            conflict = _merge_conflict(candidate, verified, queried_kind)
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
                confirmed = True
                fields['title'] = verified.title or fields['title']
                if verified.authors:
                    fields['authors'] = [str(author) for author in verified.authors]
                for field in ('abstract', 'year', 'venue', 'volume', 'issue', 'pages'):
                    value = getattr(verified, field)
                    if value:
                        fields[field] = value
                # Only the verified record's own identifiers may be published:
                # the lookup confirmed one identifier, and any further candidate
                # seen in the text (e.g. a cited work's DOI) stays unverified and
                # must not ride along into dedup or the saved record.
                fields['doi'] = getattr(verified, 'doi', None) or None
                fields['arxiv_id'] = getattr(verified, 'arxiv_id', None) or None
    except Exception as exc:  # noqa: BLE001 — verification must never block an upload
        receipt = {**receipt, 'status': 'unavailable', 'error_type': type(exc).__name__}
    if not confirmed:
        # W01/F02: an outage, an escaping error, or a lookup that confirmed
        # nothing leaves the candidate identifiers unverified. They must never
        # reach dedup (find_duplicate) — the entry is saved independently and
        # the route marks it identity_status='unconfirmed'. The title stays
        # whatever the document itself declared.
        had_claim = bool(candidate.get('doi') or candidate.get('arxiv_id'))
        fields['doi'] = None
        fields['arxiv_id'] = None
        if had_claim and receipt.get('status') not in ('unconfirmed', 'unavailable'):
            receipt = {**receipt, 'status': 'unconfirmed', 'reason': 'unverified_identity'}
    return fields, receipt
