from io import BytesIO
from unittest.mock import patch

import fitz
import httpx
import respx
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.knowledge.recommend import OPENALEX
from app.models import Model, Provider, Summary
from app.providers.client import CompletionResult

BIBTEX = "@article{x, title = {Paper One}, author = {Alice and Bob}, year = {2024}, abstract = {A study of paper things.}}"


def test_bibtex_ingest_no_provider(client):
    res = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX})
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["title"] == "Paper One"
    assert body[0]["authors"] == ["Alice", "Bob"]
    detail = client.get(f"/api/papers/{body[0]['id']}").json()
    assert detail["summary"] is None  # no provider -> no AI summary (graceful)


def test_bibtex_dedup_by_title(client):
    client.post("/api/papers/bibtex", json={"bibtex": BIBTEX})
    client.post("/api/papers/bibtex", json={"bibtex": BIBTEX})
    assert len(client.get("/api/papers").json()) == 1


def _seed_summary_provider():
    with Session(get_engine()) as s:
        p = Provider(name="oai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", role_default="summary"))
        s.commit()


def test_bibtex_ingest_with_ai_summary(client):
    _seed_summary_provider()
    fake = CompletionResult(
        content='{"problem":"X","method":"Y","dataset":"n/a","results":"R","limitations":"L"}',
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
    )
    with patch("app.providers.client.ProviderClient.complete", return_value=fake):
        res = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX})
    assert res.status_code == 200
    pid = res.json()[0]["id"]
    detail = client.get(f"/api/papers/{pid}").json()
    assert detail["summary"]["problem"] == "X"


def test_reingest_replaces_summary_not_stacks(client):
    """Re-ingesting a duplicate re-analyzes; the detail must show the NEW summary."""
    _seed_summary_provider()
    old = CompletionResult(
        content='{"problem":"OLD","method":"","dataset":"","results":"","limitations":""}',
        prompt_tokens=1, completion_tokens=1, total_tokens=2,
    )
    with patch("app.providers.client.ProviderClient.complete", return_value=old):
        pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    assert client.get(f"/api/papers/{pid}").json()["summary"]["problem"] == "OLD"

    new = CompletionResult(
        content='{"problem":"NEW","method":"","dataset":"","results":"","limitations":""}',
        prompt_tokens=1, completion_tokens=1, total_tokens=2,
    )
    with patch("app.providers.client.ProviderClient.complete", return_value=new):
        client.post("/api/papers/bibtex", json={"bibtex": BIBTEX})  # dedup → re-analyze

    detail = client.get(f"/api/papers/{pid}").json()
    assert detail["summary"]["problem"] == "NEW"  # newest, not the stacked oldest
    with Session(get_engine()) as s:
        assert len(s.exec(select(Summary).where(Summary.paper_id == pid)).all()) == 1


def test_metadata_only_entry_skips_ai(client):
    """A title-only BibTeX entry has nothing to summarize — AI must be skipped."""
    _seed_summary_provider()
    title_only = "@article{x, title = {Just a Title}, author = {A}, year = {2024}}"
    with patch("app.providers.client.ProviderClient.complete") as mocked:
        pid = client.post("/api/papers/bibtex", json={"bibtex": title_only}).json()[0]["id"]
    assert mocked.call_count == 0
    assert client.get(f"/api/papers/{pid}").json()["summary"] is None


def test_pdf_upload(client):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A test paper on transformers and attention. ")
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    res = client.post(
        "/api/papers/pdf",
        files={"file": ("t.pdf", buf.getvalue(), "application/pdf")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "pdf"
    assert body["parse_confidence"] is not None


@respx.mock
def test_related_papers_endpoint(client):
    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    respx.get(OPENALEX).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "A Related Paper",
                        "publication_year": 2021,
                        "doi": "10.0/x",
                        "cited_by_count": 42,
                        "id": "https://openalex.org/W1",
                        "authorships": [{"author": {"display_name": "Carol"}}],
                    }
                ]
            },
        )
    )
    res = client.get(f"/api/papers/{pid}/related")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["title"] == "A Related Paper"
    assert body[0]["authors"] == ["Carol"]


def test_related_papers_404_for_missing(client):
    assert client.get("/api/papers/9999/related").status_code == 404


def test_related_papers_degrades_on_network_error(client):
    """OpenAlex must never break the UI — a dead network returns []."""
    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    with patch("app.knowledge.recommend.httpx.get", side_effect=httpx.ConnectError("offline")):
        res = client.get(f"/api/papers/{pid}/related")
    assert res.status_code == 200
    assert res.json() == []
