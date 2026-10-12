"""P1b: PDF uploads identify DOI/arXiv from the document, dedup by identifier,
and keep curated metadata when landing on an existing paper.

All network is mocked (crossref/arXiv lookups); PDFs are generated in-process
with pymupdf.
"""
import json

import fitz
import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.db.engine import get_engine
from app.ingestion.sources import FetchedPaper
from app.models import Paper


def make_pdf(text=None, meta=None):
    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    if meta:
        doc.set_metadata(meta)
    raw = doc.tobytes()
    doc.close()
    return raw


def upload(client, data, name="paper.pdf"):
    return client.post("/api/papers/pdf", files={"file": (name, data, "application/pdf")})


def total_papers(client):
    return client.get("/api/papers").json()["total"]


def mock_crossref(monkeypatch, doi="10.1038/any"):
    def fetch_crossref(identifier):
        assert identifier == doi
        return FetchedPaper(source="crossref", source_ref=identifier, doi=identifier,
                            title="Verified Title", authors=["Verified Author"],
                            abstract="Verified abstract", year=2021, venue="Nature",
                            volume="12", issue="3", pages="100--110")
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref", fetch_crossref)


def test_upload_with_doi_uses_verified_metadata_not_filename(client, monkeypatch):
    mock_crossref(monkeypatch, "10.1038/s41586-019-1234-5")
    raw = make_pdf("Intro. doi:10.1038/s41586-019-1234-5")
    res = upload(client, raw, "downloaded-paper-2024.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Verified Title"
    assert body["authors"] == ["Verified Author"]
    assert body["year"] == 2021 and body["abstract"] == "Verified abstract"
    assert body["venue"] == "Nature" and body["doi"] == "10.1038/s41586-019-1234-5"
    assert body["identity"]["status"] == "retrieved"
    assert body["identity"]["source"] == "crossref"
    assert body["identity"]["identifier"] == "10.1038/s41586-019-1234-5"


def test_same_bytes_upload_stays_one_paper(client, monkeypatch):
    mock_crossref(monkeypatch, "10.1038/s41586-019-1234-5")
    raw = make_pdf("Intro. doi:10.1038/s41586-019-1234-5")
    first = upload(client, raw, "a.pdf").json()
    second = upload(client, raw, "b.pdf")
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert total_papers(client) == 1


def test_same_doi_different_bytes_merge_into_one_paper(client, monkeypatch):
    mock_crossref(monkeypatch, "10.1038/merge")
    first = upload(client, make_pdf("Study body A. doi:10.1038/merge"), "a.pdf").json()
    second = upload(client, make_pdf("Expanded study body B. doi:10.1038/merge"), "b.pdf")
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert total_papers(client) == 1


def test_pdf_with_known_doi_attaches_to_bibtex_record_without_overwrite(client, monkeypatch):
    bibtex = ("@article{key2020, title={Bibtex Original Title}, "
              "author={Ada Lovelace and Bo Bai}, year={2020}, doi={10.1038/keepme}}")
    first = client.post("/api/papers/bibtex", json={"bibtex": bibtex}).json()[0]
    mock_crossref(monkeypatch, "10.1038/keepme")
    res = upload(client, make_pdf("Body. doi:10.1038/keepme"), "file.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == first["id"]
    assert body["title"] == "Bibtex Original Title"
    assert body["authors"] == ["Ada Lovelace", "Bo Bai"]
    assert body["year"] == 2020
    assert body["identity"]["status"] == "retrieved"
    assert total_papers(client) == 1


def test_crossref_outage_creates_paper_with_filename_title(client, monkeypatch):
    def slow(identifier):
        raise TimeoutError("crossref down")
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref", slow)
    res = upload(client, make_pdf("Body. doi:10.1038/slow"), "My Paper Title.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "My Paper Title"
    assert body["doi"] == "10.1038/slow"
    assert body["identity"]["status"] == "unavailable"
    assert body["identity"]["error_type"] == "TimeoutError"


def test_arxiv_id_stored_and_second_rendition_merges(client, monkeypatch):
    def fetch_arxiv(arxiv_id, client=None, download_pdf=True):
        assert not download_pdf
        return FetchedPaper(source="arxiv", source_ref=arxiv_id, title="Arxiv Title",
                            authors=["Arxiv Author"], abstract="Arxiv abstract",
                            year=2025, arxiv_id=arxiv_id)
    monkeypatch.setattr("app.ingestion.sources.fetch_arxiv", fetch_arxiv)
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref",
                        lambda doi: pytest.fail("crossref must not run when arXiv verified"))
    first = upload(client, make_pdf("arXiv:2508.17122v7"), "one.pdf").json()
    assert first["arxiv_id"] == "2508.17122v7"
    assert first["title"] == "Arxiv Title"
    assert first["identity"]["source"] == "arxiv" and first["identity"]["status"] == "retrieved"
    second = upload(client, make_pdf("arXiv:2508.17122v7 with extra body"), "two.pdf")
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert total_papers(client) == 1


def test_unidentified_supplementary_pdfs_stay_separate(client):
    raw1 = make_pdf("Some supplementary methods text.", meta={"title": "Supplementary information"})
    raw2 = make_pdf("Other supplementary analysis text.", meta={"title": "Supplementary information"})
    one = upload(client, raw1, "supp1.pdf").json()
    two = upload(client, raw2, "supp2.pdf").json()
    assert one["title"] == "Supplementary information"
    assert one["identity"]["status"] == "none"
    assert one["id"] != two["id"]
    assert total_papers(client) == 2


def test_persist_pdf_merge_fills_only_empty_fields(client):
    from app.ingestion.service import persist_fetched
    with Session(get_engine()) as session:
        existing = Paper(source="bibtex", title="Original title", authors_json='["Ada"]',
                         doi="10.1038/direct")
        session.add(existing)
        session.commit()
        fetched = FetchedPaper(source="pdf", source_ref="uploaded.pdf",
                               title="Verified title", authors=["Bo"], abstract="Abs",
                               year=2024, venue="Venue", doi="10.1038/direct",
                               pdf_bytes=make_pdf("Body. doi:10.1038/direct"))
        paper = persist_fetched(session, fetched, get_settings().data_dir / "pdfs")
        assert paper.id == existing.id
        assert paper.title == "Original title"
        assert json.loads(paper.authors_json) == ["Ada"]
        assert paper.year == 2024
        assert len(session.exec(select(Paper)).all()) == 1
