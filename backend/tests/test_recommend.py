import httpx
import respx

from app.knowledge.recommend import OPENALEX, search_related

OPENALEX_PAYLOAD = {
    "results": [
        {
            "title": "Attention Is All You Need",
            "publication_year": 2017,
            "doi": "10.5555/3295222.3295349",
            "cited_by_count": 100000,
            "id": "https://openalex.org/W2963403868",
            "authorships": [
                {"author": {"display_name": "Ashish Vaswani"}},
                {"author": {"display_name": "Noam Shazeer"}},
                {"author": None},  # malformed entry must be skipped, not crash
            ],
        },
        {
            "title": "BERT",
            "publication_year": 2019,
            "doi": None,
            "cited_by_count": 50000,
            "id": "https://openalex.org/W2963403869",
            "authorships": [{"author": {"display_name": "Jacob Devlin"}}],
        },
    ]
}


@respx.mock
def test_search_related_parses_results():
    respx.get(OPENALEX).mock(return_value=httpx.Response(200, json=OPENALEX_PAYLOAD))
    out = search_related("transformer attention")
    assert len(out) == 2
    first = out[0]
    assert first["title"] == "Attention Is All You Need"
    assert first["authors"] == ["Ashish Vaswani", "Noam Shazeer"]  # None authorship dropped
    assert first["year"] == 2017
    assert first["cited_by_count"] == 100000
    assert first["openalex_id"] == "https://openalex.org/W2963403868"
    # per_page bounds the request AND the returned slice
    respx.get(OPENALEX).mock(return_value=httpx.Response(200, json=OPENALEX_PAYLOAD))
    assert len(search_related("x", per_page=1)) == 1


def test_search_related_empty_title_returns_empty():
    assert search_related("") == []
    assert search_related("   ") == []


@respx.mock
def test_search_related_network_error_degrades_to_empty():
    respx.get(OPENALEX).mock(side_effect=httpx.ConnectError("offline"))
    assert search_related("anything") == []


@respx.mock
def test_search_related_http_error_degrades_to_empty():
    respx.get(OPENALEX).mock(return_value=httpx.Response(503))
    assert search_related("anything") == []


@respx.mock
def test_search_related_sends_search_param():
    route = respx.get(OPENALEX).mock(return_value=httpx.Response(200, json={"results": []}))
    search_related("Graph Neural Networks", per_page=7)
    assert route.called
    request, _ = route.calls.last
    assert request.url.params["search"] == "Graph Neural Networks"
    assert request.url.params["per-page"] == "7"
