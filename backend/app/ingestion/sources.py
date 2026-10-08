import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

_crossref_lock = Lock()
_crossref_next_request_at = 0.0


@dataclass
class FetchedPaper:
    """A paper fetched from a source, before persistence/analysis."""

    source: str  # arxiv | bibtex | manual
    source_ref: str | None = None
    citation_key: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    pdf_bytes: bytes | None = None  # None when full text is unavailable
    pdf_file: Path | None = None  # Streamed downloads need not be held in RAM.


_MAX_PDF_REDIRECTS = 5


def _download_pdf(pdf_url: str) -> bytes:
    """Download the PDF, re-validating every redirect hop against arXiv.

    ``follow_redirects`` stays off so a 301/302 cannot bounce the fetcher
    onto an arbitrary host: each ``Location`` is resolved with
    :func:`urllib.parse.urljoin` (relative locations against the current
    URL) and passed through :func:`ensure_arxiv_url` *before* the next
    request, which itself goes through :func:`validated_get` (the app-wide
    outbound-GET choke point). The first response that is not a redirect is
    checked with ``raise_for_status`` and its content returned. More than
    ``_MAX_PDF_REDIRECTS`` hops raises ``ValueError``.
    """
    from urllib.parse import urljoin

    from app.security.url_guard import ensure_arxiv_url, validated_get

    url = pdf_url
    for _hop in range(_MAX_PDF_REDIRECTS):
        ensure_arxiv_url(url)
        resp = validated_get(url, timeout=60.0, follow_redirects=False)
        if not resp.is_redirect:
            resp.raise_for_status()
            return resp.content
        location = resp.headers.get("location", "")
        if not location:
            raise ValueError(f"arxiv pdf redirect from {url!r} has no Location header")
        url = urljoin(url, location)
    raise ValueError(f"arxiv pdf download exceeded {_MAX_PDF_REDIRECTS} redirects")


def normalize_arxiv_id(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/", "", value, flags=re.I)
    value = re.sub(r"^arxiv:\s*", "", value, flags=re.I)
    value = re.sub(r"\.pdf$", "", value, flags=re.I)
    if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z-]+(?:\.[A-Z]{2})?/\d{7})(?:v[1-9]\d*)?", value):
        raise ValueError("请输入有效的 arXiv 编号（如 1706.03762）或 arXiv 论文链接。")
    return value


def fetch_arxiv(arxiv_id: str, client=None, *, download_pdf: bool = True) -> FetchedPaper:
    """Fetch a paper's metadata and, by default, PDF from ArXiv.

    ``download_pdf=False`` reuses metadata parsing when another import path
    already streams the PDF to disk.

    ``client`` is injectable for testing (an object with a ``results(search)``
    method yielding objects with ``title/authors/summary/published/doi`` and,
    for a real ``arxiv.Result``, a ``get_short_id()`` method).

    The PDF URL is always the canonical constant
    ``https://arxiv.org/pdf/{short_id}`` built from ``result.get_short_id()``
    (e.g. ``2405.00001v2``), falling back to the ``arxiv_id`` argument — the
    API-provided ``pdf_url`` is never used.
    """
    import arxiv

    arxiv_id = normalize_arxiv_id(arxiv_id)
    client = client or arxiv.Client()
    result = next(client.results(arxiv.Search(id_list=[arxiv_id])))

    short_id = None
    get_short_id = getattr(result, "get_short_id", None)
    if callable(get_short_id):
        short_id = get_short_id()
    if not short_id:
        short_id = arxiv_id
    # Direct-PDF acquisition already streams this file; reuse metadata lookup
    # without fetching a second in-memory copy of the same PDF.
    pdf_bytes = _download_pdf(f"https://arxiv.org/pdf/{short_id}") if download_pdf else None

    published = getattr(result, "published", None)
    year = published.year if published else None
    return FetchedPaper(
        source="arxiv",
        source_ref=arxiv_id,
        title=result.title,
        authors=[str(a) for a in result.authors],
        abstract=result.summary,
        year=year,
        doi=getattr(result, "doi", None),
        arxiv_id=arxiv_id,
        pdf_bytes=pdf_bytes,
    )


def parse_bibtex(bibtex_text: str) -> list[FetchedPaper]:
    """Parse a BibTeX string into a list of FetchedPaper (metadata only)."""
    import bibtexparser

    db = bibtexparser.loads(bibtex_text)
    out: list[FetchedPaper] = []
    for entry in db.entries:
        raw_authors = entry.get("author", "")
        authors = [a.strip() for a in re.split(r"\s+and\s+", raw_authors) if a.strip()]
        raw_year = entry.get("year", "")
        year = int(raw_year) if raw_year.isdigit() else None
        doi = entry.get("doi") or entry.get("DOI") or None
        out.append(
            FetchedPaper(
                source="bibtex",
                source_ref=entry.get("ID"),
                citation_key=entry.get("ID"),
                title=entry.get("title"),
                authors=authors,
                abstract=entry.get("abstract") or entry.get("abstractNote"),
                year=year,
                venue=entry.get("journal") or entry.get("booktitle"),
                volume=entry.get("volume"),
                issue=entry.get("number"),
                pages=entry.get("pages"),
                doi=doi,
                arxiv_id=entry.get("eprint") or None,
                pdf_bytes=None,
            )
        )
    return out


def _ris_records(ris_text: str) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    last_tag: str | None = None
    for raw_line in ris_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        match = re.match(r"^([A-Za-z0-9]{2})  - ?(.*)$", line)
        if match:
            tag = match.group(1).upper()
            value = match.group(2).strip()
            if tag == "TY":
                current = {"TY": [value]}
                last_tag = "TY"
                continue
            if current is None:
                continue
            if tag == "ER":
                records.append(current)
                current = None
                last_tag = None
                continue
            current.setdefault(tag, []).append(value)
            last_tag = tag
        elif current is not None and last_tag:
            current[last_tag][-1] = f"{current[last_tag][-1]} {line.strip()}".strip()
    if current:
        records.append(current)
    return records


def _first(record: dict[str, list[str]], *tags: str) -> str | None:
    for tag in tags:
        values = record.get(tag)
        if values:
            text = values[0].strip()
            if text:
                return text
    return None


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{4}", value)
    return int(match.group(0)) if match else None


def _arxiv_id(record: dict[str, list[str]]) -> str | None:
    haystack = []
    for tag in ("UR", "N1", "M3"):
        haystack.extend(record.get(tag, []))
    for text in haystack:
        match = re.search(r"(?:arxiv[:/ ]|abs/)([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _ris_pages(record: dict[str, list[str]]) -> str | None:
    start, end = _first(record, "SP"), _first(record, "EP")
    if start and end and start != end:
        return f"{start}--{end}"
    return start or end


def normalize_doi(value: str | None) -> str | None:
    """Normalize a DOI supplied as an identifier or a standard resolver URL."""
    from urllib.parse import unquote
    value = (value or "").strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    value = unquote(value).strip()
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def fetch_crossref(doi: str) -> FetchedPaper:
    """Retrieve DOI metadata without losing publication dates or article numbers."""
    from urllib.parse import quote
    from app.security.url_guard import validated_get
    identifier = normalize_doi(doi)
    if identifier is None:
        raise ValueError("Invalid DOI")
    url = f"https://api.crossref.org/works/{quote(identifier, safe='')}"
    # Crossref's public pool permits one in-flight request (since Dec 2025).
    # Survey workers and agent imports share this process, so pace the common
    # lookup rather than allowing independent jobs to race each other.
    global _crossref_next_request_at
    with _crossref_lock:
        delay = _crossref_next_request_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        try:
            response = validated_get(url, headers={"Accept": "application/json",
                "User-Agent": "PaperMind (local research library)"}, timeout=15)
        finally:
            _crossref_next_request_at = time.monotonic() + 0.25
    response.raise_for_status()
    record = response.json().get('message')
    if not isinstance(record, dict) or normalize_doi(record.get('DOI')) != identifier:
        raise ValueError("Crossref did not return the requested DOI")

    def first_text(value):
        if isinstance(value, list):
            value = next((v for v in value if isinstance(v, str) and v.strip()), None)
        return value.strip() if isinstance(value, str) and value.strip() else None

    authors = []
    for author in record.get('author') or []:
        if not isinstance(author, dict):
            continue
        family, given = first_text(author.get('family')), first_text(author.get('given'))
        name = ', '.join(v for v in (family, given) if v) or first_text(author.get('name'))
        if name:
            authors.append(name)

    # A journal's assigned print issue can follow online-first publication in
    # the previous year. Use the issue date when the publisher supplied one;
    # online-only records retain their online/issued date. Never infer from DOI.
    year = None
    for field in ('published-print', 'published-online', 'issued', 'published'):
        date = record.get(field)
        parts = date.get('date-parts') if isinstance(date, dict) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            value = parts[0][0]
            if isinstance(value, int) and not isinstance(value, bool) and 1000 <= value <= 9999:
                year = value
                break
    return FetchedPaper(
        source='crossref', source_ref=identifier, doi=identifier,
        title=first_text(record.get('title')), authors=authors, year=year,
        venue=first_text(record.get('container-title')),
        volume=first_text(record.get('volume')), issue=first_text(record.get('issue')),
        pages=first_text(record.get('page')) or first_text(record.get('article-number')),
    )


def lookup_doi_metadata(doi: str | None) -> tuple[FetchedPaper | None, dict | None]:
    """Shared best-effort lookup; unavailable metadata never aborts an import."""
    identifier = normalize_doi(doi)
    if identifier is None:
        return None, None
    receipt = {'source': 'crossref', 'identifier': identifier}
    try:
        return fetch_crossref(identifier), {**receipt, 'status': 'retrieved'}
    except Exception as exc:
        return None, {**receipt, 'status': 'unavailable', 'error_type': type(exc).__name__}


def parse_ris(ris_text: str) -> list[FetchedPaper]:
    """Parse RIS records exported by Zotero/EndNote into FetchedPaper rows."""
    out: list[FetchedPaper] = []
    for index, record in enumerate(_ris_records(ris_text), start=1):
        title = _first(record, "TI", "T1", "CT")
        if not title:
            continue
        authors = []
        for tag in ("AU", "A1"):
            authors.extend([value.strip() for value in record.get(tag, []) if value.strip()])
        source_ref = _first(record, "ID") or f"ris-{index}"
        out.append(
            FetchedPaper(
                source="ris",
                source_ref=source_ref,
                title=title,
                authors=authors,
                abstract=_first(record, "AB", "N2"),
                year=_year(_first(record, "PY", "Y1", "DA")),
                venue=_first(record, "JO", "JF", "T2", "JA", "J2"),
                volume=_first(record, "VL"),
                issue=_first(record, "IS"),
                pages=_ris_pages(record),
                doi=_first(record, "DO"),
                arxiv_id=_arxiv_id(record),
                pdf_bytes=None,
            )
        )
    return out
