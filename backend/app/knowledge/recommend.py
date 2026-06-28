import httpx

OPENALEX = "https://api.openalex.org/works"


def search_related(title: str, per_page: int = 5) -> list[dict]:
    """Find related works via OpenAlex (free, no API key).

    Returns a list of {title, authors, year, doi, cited_by_count, openalex_id}.
    Network/parse errors degrade to an empty list (never raises).
    """
    if not title:
        return []
    try:
        resp = httpx.get(
            OPENALEX,
            params={"search": title, "per-page": per_page},
            timeout=15.0,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception:  # noqa: BLE001 — external discovery must never break ingest/UI
        return []

    out: list[dict] = []
    for work in results[:per_page]:
        authors = [
            a["author"]["display_name"]
            for a in work.get("authorships", [])
            if a.get("author")
        ]
        out.append(
            {
                "title": work.get("title"),
                "authors": authors[:5],
                "year": work.get("publication_year"),
                "doi": work.get("doi"),
                "cited_by_count": work.get("cited_by_count", 0),
                "openalex_id": work.get("id"),
            }
        )
    return out
