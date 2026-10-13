"""P1b: PDF uploads identify DOI/arXiv from the document, dedup by identifier,
and keep curated metadata when landing on an existing paper.

All network is mocked (crossref/arXiv lookups); PDFs are generated in-process
with pymupdf.
"""
import json
from pathlib import Path

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


def test_same_doi_different_bytes_keeps_stored_pdf(client, monkeypatch):
    mock_crossref(monkeypatch, "10.1038/merge")
    first_raw = make_pdf("Study body A. doi:10.1038/merge")
    first = upload(client, first_raw, "a.pdf").json()
    second = upload(client, make_pdf("Expanded study body B. doi:10.1038/merge"), "b.pdf")
    assert second.status_code == 200
    body = second.json()
    assert body["id"] == first["id"]
    assert body["identity"]["pdf"] == "kept_existing"
    assert total_papers(client) == 1
    with Session(get_engine()) as session:
        stored = Path(session.get(Paper, first["id"]).pdf_path).read_bytes()
    assert stored == first_raw


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


def test_persist_pdf_merge_fills_authors_when_list_empty(client):
    from app.ingestion.service import persist_fetched
    with Session(get_engine()) as session:
        existing = Paper(source="bibtex", title="Empty authors", authors_json="[]",
                         doi="10.1038/empty")
        session.add(existing)
        session.commit()
        fetched = FetchedPaper(source="pdf", source_ref="uploaded.pdf", title=None,
                               authors=["Bo Bai"], doi="10.1038/empty",
                               pdf_bytes=make_pdf("Body. doi:10.1038/empty"))
        paper = persist_fetched(session, fetched, get_settings().data_dir / "pdfs")
        assert paper.id == existing.id
        assert json.loads(paper.authors_json) == ["Bo Bai"]


# --- R01: 参考文献中的 DOI 不是上传文档的身份，不得据此误归并 ----------------

CITED_BIBTEX = ("@article{cited, title={Cited Earlier Work}, author={A. Author}, "
                "year={2019}, doi={10.1234/cited-paper}}")


def make_pages_pdf(pages, meta=None):
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        for index, line in enumerate(lines):
            page.insert_text((72, 72 + 16 * index), line)
    if meta:
        doc.set_metadata(meta)
    raw = doc.tobytes()
    doc.close()
    return raw


def mock_crossref_map(monkeypatch, mapping):
    def fetch_crossref(identifier):
        item = mapping[identifier]
        return FetchedPaper(source="crossref", source_ref=identifier, doi=identifier,
                            title=item["title"], authors=item.get("authors", []),
                            abstract=item.get("abstract"), year=item.get("year"),
                            venue=item.get("venue"))
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref", fetch_crossref)


def get_paper(client, paper_id):
    return client.get(f"/api/papers/{paper_id}").json()


REPRO_PAGES = [
    ["Actual New Paper", "This study is available as 10.1234/actual-paper."],
    ["References", "A. Author 2019. 10.1234/cited-paper."],
]


def test_reference_list_doi_does_not_hijack_upload(client, monkeypatch):
    cited = client.post("/api/papers/bibtex", json={"bibtex": CITED_BIBTEX}).json()[0]
    mock_crossref_map(monkeypatch, {
        "10.1234/cited-paper": {"title": "Cited Earlier Work", "year": 2019},
        "10.1234/actual-paper": {"title": "Actual New Paper", "year": 2026},
    })
    raw = make_pages_pdf(REPRO_PAGES)
    res = upload(client, raw, "actual-paper.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != cited["id"]
    assert body["title"] == "Actual New Paper"
    assert body["doi"] == "10.1234/actual-paper"
    assert body["identity"]["status"] == "retrieved"
    assert body["has_pdf"] is True
    assert total_papers(client) == 2
    # 被引用论文的标题、标识与 PDF 关联完全不变。
    cited_now = get_paper(client, cited["id"])
    assert cited_now["title"] == "Cited Earlier Work"
    assert cited_now["doi"] == "10.1234/cited-paper"
    assert cited_now["has_pdf"] is False
    with Session(get_engine()) as session:
        stored = Path(session.get(Paper, body["id"]).pdf_path).read_bytes()
    assert stored == raw


def test_cited_paper_with_pdf_keeps_bytes_and_new_document_survives(client, monkeypatch):
    client.post("/api/papers/bibtex", json={"bibtex": CITED_BIBTEX})
    mock_crossref_map(monkeypatch, {
        "10.1234/cited-paper": {"title": "Cited Earlier Work", "year": 2019},
        "10.1234/actual-paper": {"title": "Actual New Paper", "year": 2026},
    })
    cited_pdf = make_pdf("Body. doi:10.1234/cited-paper")
    first = upload(client, cited_pdf, "cited.pdf").json()
    raw = make_pages_pdf(REPRO_PAGES)
    res = upload(client, raw, "actual-paper.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != first["id"]
    assert body["has_pdf"] is True
    assert total_papers(client) == 2
    with Session(get_engine()) as session:
        kept = Path(session.get(Paper, first["id"]).pdf_path).read_bytes()
        fresh = session.get(Paper, body["id"])
        fresh_path = fresh.pdf_path
        fresh_title = fresh.title
    assert kept == cited_pdf
    assert fresh_path
    assert Path(fresh_path).read_bytes() == raw
    assert fresh_title == "Actual New Paper"


def test_metadata_title_conflict_saves_independent_unconfirmed(client, monkeypatch):
    impostor = client.post("/api/papers/bibtex", json={"bibtex": (
        "@article{imp, title={Impostor Record}, author={B. Beta}, year={2018}, "
        "doi={10.1234/actual-paper}}")}).json()[0]
    mock_crossref_map(monkeypatch, {
        "10.1234/actual-paper": {"title": "Impostor Record", "year": 2018},
    })
    raw = make_pdf("Body. doi:10.1234/actual-paper", meta={"title": "Actual New Paper"})
    res = upload(client, raw, "actual.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != impostor["id"]
    assert body["title"] == "Actual New Paper"
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unconfirmed"
    assert body["identity"]["reason"] == "title_conflict"
    assert total_papers(client) == 2
    assert get_paper(client, impostor["id"])["has_pdf"] is False
    with Session(get_engine()) as session:
        fresh = session.get(Paper, body["id"])
        assert Path(fresh.pdf_path).read_bytes() == raw


def test_reference_only_doi_never_auto_merges(client, monkeypatch):
    cited = client.post("/api/papers/bibtex", json={"bibtex": CITED_BIBTEX}).json()[0]
    mock_crossref_map(monkeypatch, {
        "10.1234/cited-paper": {"title": "Cited Earlier Work", "year": 2019},
    })
    raw = make_pages_pdf([
        ["A short study text without any self identifier."],
        ["References", "A. Author 2019. 10.1234/cited-paper."],
    ])
    res = upload(client, raw, "notes.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != cited["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unconfirmed"
    assert body["identity"]["reason"] == "unverified_title"
    assert total_papers(client) == 2
    assert get_paper(client, cited["id"])["has_pdf"] is False


def test_cited_arxiv_id_does_not_hijack_upload(client, monkeypatch):
    old = client.post("/api/papers/manual", json={
        "title": "Attention Old Work", "arxiv_id": "1706.03762"}).json()
    def fetch_arxiv(arxiv_id, client=None, download_pdf=True):
        assert not download_pdf
        titles = {"1706.03762": "Attention Old Work",
                  "2601.00001v1": "Extending Prior Approaches"}
        return FetchedPaper(source="arxiv", source_ref=arxiv_id, title=titles[arxiv_id],
                            authors=["D. Dao"], abstract="Abs", year=2026,
                            arxiv_id=arxiv_id)
    monkeypatch.setattr("app.ingestion.sources.fetch_arxiv", fetch_arxiv)
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref",
                        lambda doi: pytest.fail("crossref must not run when arXiv verified"))
    raw = make_pages_pdf([
        ["Extending Prior Approaches", "We build on arXiv:1706.03762.",
         "arXiv:2601.00001v1"],
        ["References", "arXiv:1706.03762"],
    ])
    res = upload(client, raw, "ext.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != old["id"]
    assert body["title"] == "Extending Prior Approaches"
    assert body["arxiv_id"] == "2601.00001v1"
    assert body["identity"]["status"] == "retrieved"
    assert total_papers(client) == 2
    assert get_paper(client, old["id"])["has_pdf"] is False
