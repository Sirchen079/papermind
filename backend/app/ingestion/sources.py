import re
from dataclasses import dataclass, field


@dataclass
class FetchedPaper:
    """A paper fetched from a source, before persistence/analysis."""

    source: str  # arxiv | bibtex | manual
    source_ref: str | None = None
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

        pdf_bytes = httpx.get(result.pdf_url, timeout=60.0, follow_redirects=True).content

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
