import httpx

OPENALEX = "https://api.openalex.org/works"


class DiscoveryError(RuntimeError):
    def __init__(self, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def search_related(title: str, per_page: int = 5) -> list[dict]:
    """Find related works via OpenAlex (free, no API key).

    Returns a list of {title, authors, year, doi, cited_by_count, openalex_id}.
    Empty results and external failures are distinct, so users can retry.
    """
    if not title.strip():
        return []
    try:
        resp = httpx.get(
            OPENALEX,
            params={"search": title, "per-page": per_page},
            timeout=15.0,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not isinstance(results, list):
            raise ValueError("invalid results")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise DiscoveryError("相关研究服务请求过多，请稍后重试。", exc.response.headers.get("retry-after")) from exc
        raise DiscoveryError("相关研究服务暂时不可用，请稍后重试。") from exc
    except (httpx.RequestError, ValueError, TypeError) as exc:
        raise DiscoveryError("无法获取相关研究，请检查网络后重试。") from exc

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
