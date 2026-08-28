import re
from dataclasses import dataclass, field


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
    doi: str | None = None
    arxiv_id: str | None = None
    pdf_bytes: bytes | None = None  # None when full text is unavailable


def fetch_arxiv(arxiv_id: str, client=None) -> FetchedPaper:
    """Fetch a paper's metadata + PDF from ArXiv.

    ``client`` is injectable for testing (an object with a ``results(search)``
    method yielding objects with ``title/authors/summary/published/pdf_url/doi``).
    """
    import arxiv

    client = client or arxiv.Client()
    result = next(client.results(arxiv.Search(id_list=[arxiv_id])))

    pdf_bytes = None
    if result.pdf_url:
        import httpx

        resp = httpx.get(result.pdf_url, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        pdf_bytes = resp.content

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
                doi=_first(record, "DO"),
                arxiv_id=_arxiv_id(record),
                pdf_bytes=None,
            )
        )
    return out
