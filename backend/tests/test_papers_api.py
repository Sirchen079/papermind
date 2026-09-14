import logging
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import fitz
import httpx
import respx
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.knowledge.recommend import OPENALEX
from app.models import Model, Paper, Provider, Summary
from app.providers.client import CompletionResult

BIBTEX = "@article{x, title = {Paper One}, author = {Alice and Bob}, year = {2024}, abstract = {A study of paper things.}}"


def test_manual_paper_create_without_provider(client):
    res = client.post(
        "/api/papers/manual",
        json={
            "citation_key": "zhang2026graph",
            "title": "  面向科研论文的中文知识图谱综述  ",
            "authors": [" 张三 ", "李四", ""],
            "year": 2026,
            "venue": "软件学报",
            "doi": "10.1234/manual",
            "arxiv_id": "2601.00001",
            "abstract": "这是一篇手动录入的论文摘要。",
        },
    )

    assert res.status_code == 201
    body = res.json()
    assert body["source"] == "manual"
    assert body["citation_key"] == "zhang2026graph"
    assert body["title"] == "面向科研论文的中文知识图谱综述"
    assert body["authors"] == ["张三", "李四"]
    assert body["year"] == 2026
    assert body["venue"] == "软件学报"
    assert body["doi"] == "10.1234/manual"
    assert body["arxiv_id"] == "2601.00001"
    assert body["abstract"] == "这是一篇手动录入的论文摘要。"

    detail = client.get(f"/api/papers/{body['id']}").json()
    assert detail["summary"] is None
    assert detail["reading"]["status"] == "unread"
    assert detail["tags"] == []
    assert detail["collections"] == []


def test_manual_paper_create_rejects_missing_title_and_duplicate_identifiers(client):
    empty = client.post("/api/papers/manual", json={"title": "   "})
    assert empty.status_code == 422
    assert "title is required" in empty.text

    first = client.post(
        "/api/papers/manual",
        json={
            "citation_key": "manual2026",
            "title": "Manual Seed Paper",
            "doi": "10.1234/manual-dup",
            "arxiv_id": "2601.00002",
        },
    )
    assert first.status_code == 201

    duplicate_key = client.post(
        "/api/papers/manual",
        json={"citation_key": "manual2026", "title": "Other Manual Key Paper"},
    )
    assert duplicate_key.status_code == 422
    assert "citation key already exists" in duplicate_key.text

    duplicate_doi = client.post(
        "/api/papers/manual",
        json={"title": "Other Manual DOI Paper", "doi": "10.1234/manual-dup"},
    )
    assert duplicate_doi.status_code == 422
    assert "doi already exists" in duplicate_doi.text

    duplicate_arxiv = client.post(
        "/api/papers/manual",
        json={"title": "Other Manual Arxiv Paper", "arxiv_id": "2601.00002"},
    )
    assert duplicate_arxiv.status_code == 422
    assert "arxiv id already exists" in duplicate_arxiv.text


def test_manual_paper_citation_matching_failure_logs_warning(client, caplog):
    """Citation backfill after a manual entry stays best-effort (201 + paper
    created), but the failure must surface as a WARNING with the stable step
    name, the paper id, and the exception attached — no exception text in the
    message itself."""
    with caplog.at_level(logging.WARNING, logger="app.api.papers_api"):
        with patch(
            "app.ingestion.citation_match.match_citations_for_paper",
            side_effect=RuntimeError("boom"),
        ):
            res = client.post(
                "/api/papers/manual",
                json={"title": "Backfill Failure Paper", "year": 2026},
            )

    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Backfill Failure Paper"

    records = [r for r in caplog.records if r.name == "app.api.papers_api"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert "manual_citation_matching" in record.getMessage()
    assert str(body["id"]) in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


def test_bibtex_ingest_no_provider(client):
    res = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX})
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["citation_key"] == "x"
    assert body[0]["title"] == "Paper One"
    assert body[0]["authors"] == ["Alice", "Bob"]
    detail = client.get(f"/api/papers/{body[0]['id']}").json()
    assert detail["citation_key"] == "x"
    assert detail["summary"] is None  # no provider -> no AI summary (graceful)


def test_bibtex_ingest_does_not_store_duplicate_active_citation_keys(client):
    """P10.4 契约：bibtex key 冲突时不再存 None，而是自动生成稳定 key。

    原断言（second 为 None）与 P10.4「入库自动生成 citation_key」矛盾，
    按新契约更新：第二篇仍不能占用 dupkey，但获得生成的 bo2025second。
    """
    bibtex = """
@article{dupkey, title = {First Keyed Paper}, author = {Ada}, year = {2024}}
@article{dupkey, title = {Second Keyed Paper}, author = {Bo}, year = {2025}}
"""

    res = client.post("/api/papers/bibtex", json={"bibtex": bibtex})

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2
    first_id = next(item["id"] for item in body if item["title"] == "First Keyed Paper")
    second_id = next(item["id"] for item in body if item["title"] == "Second Keyed Paper")
    assert client.get(f"/api/papers/{first_id}").json()["citation_key"] == "dupkey"
    second = client.get(f"/api/papers/{second_id}").json()["citation_key"]
    assert second is not None and second != "dupkey"
    assert second == "bo2025second"


def test_bibtex_ingest_does_not_store_invalid_citation_key(client):
    """P10.4 契约：非法 bibtex key 不落库，但会自动生成合法稳定 key。

    原断言（None）与 P10.4 自动生成矛盾，按新契约更新为生成的键。
    """
    bibtex = "@article{bad$key, title = {Invalid Key Paper}, author = {Ada}, year = {2024}}"

    res = client.post("/api/papers/bibtex", json={"bibtex": bibtex})

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    detail = client.get(f"/api/papers/{body[0]['id']}").json()
    assert detail["title"] == "Invalid Key Paper"
    assert detail["citation_key"] == "ada2024invalid"


def test_patch_paper_metadata_updates_citation_key_and_fields(client):
    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]

    res = client.patch(
        f"/api/papers/{pid}",
        json={
            "citation_key": "smith2025retrieval",
            "title": "Updated Retrieval Paper",
            "authors": ["Jane Smith", "Bo Chen"],
            "year": 2025,
            "venue": "SIGIR",
            "doi": "10.1234/updated",
            "arxiv_id": "2501.12345",
            "abstract": "Updated abstract.",
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["citation_key"] == "smith2025retrieval"
    assert body["title"] == "Updated Retrieval Paper"
    assert body["authors"] == ["Jane Smith", "Bo Chen"]
    assert body["year"] == 2025
    assert body["venue"] == "SIGIR"
    assert body["doi"] == "10.1234/updated"
    assert body["arxiv_id"] == "2501.12345"
    assert body["abstract"] == "Updated abstract."


def test_patch_paper_metadata_rejects_duplicate_and_invalid_citation_keys(client):
    first = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    second = client.post(
        "/api/papers/bibtex",
        json={"bibtex": "@article{y, title = {Paper Two}, author = {Carol}, year = {2025}}"},
    ).json()[0]["id"]

    duplicate = client.patch(f"/api/papers/{second}", json={"citation_key": "x"})
    assert duplicate.status_code == 422
    assert "citation key already exists" in duplicate.text

    invalid = client.patch(f"/api/papers/{first}", json={"citation_key": "bad key"})
    assert invalid.status_code == 422
    assert "invalid citation key" in invalid.text


def test_patch_paper_metadata_rejects_duplicate_doi(client):
    first = client.post(
        "/api/papers/bibtex",
        json={"bibtex": "@article{first, title = {First Paper}, author = {Ada}, doi = {10.1234/same}}"},
    ).json()[0]["id"]
    second = client.post(
        "/api/papers/bibtex",
        json={"bibtex": "@article{second, title = {Second Paper}, author = {Bo}, doi = {10.1234/other}}"},
    ).json()[0]["id"]

    duplicate = client.patch(f"/api/papers/{second}", json={"doi": "10.1234/same"})

    assert duplicate.status_code == 422
    assert "doi already exists" in duplicate.text
    assert client.get(f"/api/papers/{first}").json()["doi"] == "10.1234/same"
    assert client.get(f"/api/papers/{second}").json()["doi"] == "10.1234/other"


def test_patch_paper_metadata_rejects_duplicate_arxiv_id(client):
    first = client.post(
        "/api/papers/bibtex",
        json={"bibtex": "@article{first, title = {First Arxiv Paper}, author = {Ada}, eprint = {2405.00001}}"},
    ).json()[0]["id"]
    second = client.post(
        "/api/papers/bibtex",
        json={"bibtex": "@article{second, title = {Second Arxiv Paper}, author = {Bo}, eprint = {2405.00002}}"},
    ).json()[0]["id"]

    duplicate = client.patch(f"/api/papers/{second}", json={"arxiv_id": "2405.00001"})

    assert duplicate.status_code == 422
    assert "arxiv id already exists" in duplicate.text
    assert client.get(f"/api/papers/{first}").json()["arxiv_id"] == "2405.00001"
    assert client.get(f"/api/papers/{second}").json()["arxiv_id"] == "2405.00002"


def test_bibtex_dedup_by_title(client):
    client.post("/api/papers/bibtex", json={"bibtex": BIBTEX})
    client.post("/api/papers/bibtex", json={"bibtex": BIBTEX})
    assert len(client.get("/api/papers").json()["items"]) == 1


def test_bibtex_reimport_ignores_soft_deleted_doi_duplicate(client):
    bibtex = (
        "@article{old, title = {Old Deleted Paper}, author = {Alice}, "
        "year = {2024}, doi = {10.1234/reimport}}"
    )
    old_id = client.post("/api/papers/bibtex", json={"bibtex": bibtex}).json()[0]["id"]

    assert client.delete(f"/api/papers/{old_id}").status_code == 204

    new_bibtex = (
        "@article{new, title = {Reimported Paper}, author = {Alice}, "
        "year = {2025}, doi = {10.1234/reimport}}"
    )
    res = client.post("/api/papers/bibtex", json={"bibtex": new_bibtex})

    assert res.status_code == 200
    new_id = res.json()[0]["id"]
    assert new_id != old_id
    visible = client.get("/api/papers").json()["items"]
    assert [paper["title"] for paper in visible] == ["Reimported Paper"]
    with Session(get_engine()) as s:
        old = s.get(Paper, old_id)
        new = s.get(Paper, new_id)
        assert old.is_deleted is True
        assert new.is_deleted is False


def test_arxiv_reimport_ignores_soft_deleted_arxiv_duplicate(client, monkeypatch):
    from app.ingestion.sources import FetchedPaper

    def old_fetch(arxiv_id: str) -> FetchedPaper:
        return FetchedPaper(
            source="arxiv",
            source_ref=arxiv_id,
            title="Old Deleted Arxiv Paper",
            authors=["Alice"],
            year=2024,
            arxiv_id=arxiv_id,
        )

    monkeypatch.setattr("app.api.papers_api.fetch_arxiv", old_fetch)
    old_id = client.post("/api/papers/arxiv", json={"arxiv_id": "2405.00001"}).json()["id"]

    assert client.delete(f"/api/papers/{old_id}").status_code == 204

    def new_fetch(arxiv_id: str) -> FetchedPaper:
        return FetchedPaper(
            source="arxiv",
            source_ref=arxiv_id,
            title="Reimported Arxiv Paper",
            authors=["Alice"],
            year=2025,
            arxiv_id=arxiv_id,
        )

    monkeypatch.setattr("app.api.papers_api.fetch_arxiv", new_fetch)
    res = client.post("/api/papers/arxiv", json={"arxiv_id": "2405.00001"})

    assert res.status_code == 200
    new_id = res.json()["id"]
    assert new_id != old_id
    visible = client.get("/api/papers").json()["items"]
    assert [paper["title"] for paper in visible] == ["Reimported Arxiv Paper"]
    with Session(get_engine()) as s:
        old = s.get(Paper, old_id)
        new = s.get(Paper, new_id)
        assert old.is_deleted is True
        assert new.is_deleted is False


def test_papers_list_tolerates_malformed_authors_json(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Malformed Authors List Paper", authors_json="not-json")
        session.add(paper)
        session.commit()
        pid = paper.id

    res = client.get("/api/papers")

    assert res.status_code == 200
    row = next(item for item in res.json()["items"] if item["id"] == pid)
    assert row["authors"] == []


def _seed_papers(count: int, title_prefix: str = "Paged Paper") -> list[int]:
    with Session(get_engine()) as session:
        papers = [
            Paper(source="manual", title=f"{title_prefix} {i:02d}") for i in range(count)
        ]
        session.add_all(papers)
        session.commit()
        return [p.id for p in papers]


def test_papers_list_paginates_with_total(client):
    ids = _seed_papers(5)  # list is id DESC -> reversed insertion order
    expected = list(reversed(ids))

    page1 = client.get("/api/papers", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/api/papers", params={"limit": 2, "offset": 2}).json()
    page3 = client.get("/api/papers", params={"limit": 2, "offset": 4}).json()

    assert [p["id"] for p in page1["items"]] == expected[:2]
    assert [p["id"] for p in page2["items"]] == expected[2:4]
    assert [p["id"] for p in page3["items"]] == expected[4:]
    for page in (page1, page2, page3):
        assert page["total"] == 5
    assert (page3["limit"], page3["offset"]) == (2, 4)


def test_papers_list_defaults_to_limit_100(client):
    _seed_papers(3)

    body = client.get("/api/papers").json()

    assert len(body["items"]) == 3
    assert (body["limit"], body["offset"], body["total"]) == (100, 0, 3)


def test_papers_list_offset_beyond_total_returns_empty_with_total(client):
    _seed_papers(2)

    body = client.get("/api/papers", params={"limit": 10, "offset": 50}).json()

    assert body["items"] == []
    assert body["total"] == 2


def test_papers_list_window_crossing_total_returns_partial(client):
    ids = _seed_papers(4)

    body = client.get("/api/papers", params={"limit": 3, "offset": 2}).json()

    # id DESC order is [4,3,2,1]; window [2:5] returns the last two papers only.
    assert [p["id"] for p in body["items"]] == [ids[1], ids[0]]
    assert body["total"] == 4


def test_papers_list_validates_limit_and_offset(client):
    for params in ({"limit": 0}, {"limit": 501}, {"limit": -1}, {"offset": -1}):
        assert client.get("/api/papers", params=params).status_code == 422


def test_papers_list_excludes_soft_deleted_from_items_and_total(client):
    ids = _seed_papers(3)
    assert client.delete(f"/api/papers/{ids[0]}").status_code == 204

    body = client.get("/api/papers", params={"limit": 10, "offset": 0}).json()

    assert body["total"] == 2
    assert [p["id"] for p in body["items"]] == list(reversed(ids[1:]))


def test_paper_detail_tolerates_malformed_summary_json(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Malformed Summary Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        session.add(Summary(paper_id=paper.id, content_json="not-json"))
        session.commit()
        pid = paper.id

    detail = client.get(f"/api/papers/{pid}")
    assert detail.status_code == 200
    assert detail.json()["summary"] is None

    listed = client.get("/api/papers")
    assert listed.status_code == 200
    row = next(item for item in listed.json()["items"] if item["id"] == pid)
    assert row["has_summary"] is False


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


def test_ris_ingest_imports_zotero_endnote_records(client):
    ris = """
TY  - JOUR
TI  - Attention Is All You Need
AU  - Ashish Vaswani
AU  - Noam Shazeer
PY  - 2017
JO  - NeurIPS
DO  - 10.5555/3295222.3295349
AB  - Transformer model
UR  - https://arxiv.org/abs/1706.03762
ER  -
"""

    res = client.post("/api/papers/ris", json={"ris": ris})

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["source"] == "ris"
    assert body[0]["title"] == "Attention Is All You Need"
    assert body[0]["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert body[0]["year"] == 2017
    assert body[0]["venue"] == "NeurIPS"
    assert body[0]["doi"] == "10.5555/3295222.3295349"
    assert body[0]["arxiv_id"] == "1706.03762"


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


def test_pdf_upload_keeps_saved_file_inside_pdf_dir(client, env):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A test paper with a hostile filename. ")
    buf = BytesIO()
    doc.save(buf)
    doc.close()

    res = client.post(
        "/api/papers/pdf",
        files={"file": ("../outside", buf.getvalue(), "application/pdf")},
    )
    assert res.status_code == 200
    pid = res.json()["id"]

    with Session(get_engine()) as s:
        paper = s.get(Paper, pid)
        assert paper is not None
        saved = Path(paper.pdf_path).resolve()

    assert saved.is_relative_to((env / "data" / "pdfs").resolve())


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


def test_related_papers_reports_network_error(client):
    """A failed lookup must not be presented as no matching research."""
    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    with patch("app.knowledge.recommend.httpx.get", side_effect=httpx.ConnectError("offline")):
        res = client.get(f"/api/papers/{pid}/related")
    assert res.status_code == 503
    assert "检查网络" in res.json()["detail"]


def _bibtex_with_abstract(title: str, abstract: str) -> str:
    return (
        f"@article{{x, title = {{{title}}}, author = {{Alice}}, year = {{2024}}, "
        f"abstract = {{{abstract}}}}}"
    )


def test_delete_paper_hides_it_and_drops_dependent_library_links(client):
    from app.models import Concept, Paper, PaperChunk, PaperConcept, PaperLink, Project

    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    # Seed a chunk + a concept link to confirm both are removed (a deleted paper
    # must not surface in RAG nor inflate the concept graph). Seed a thesis
    # link too: once the paper is hidden there is no UI surface left to detach
    # it, so it must not keep blocking project cleanup.
    with Session(get_engine()) as s:
        s.add(PaperChunk(paper_id=pid, ordinal=0, text="seed"))
        c = Concept(name="transformers", normalized_key="transformers")
        s.add(c)
        project = Project(name="Cleanup Project", kind="topic")
        s.add(project)
        s.commit()
        s.refresh(c)
        s.refresh(project)
        s.add(PaperConcept(paper_id=pid, concept_id=c.id, weight=1.0))
        s.add(PaperLink(paper_id=pid, project_id=project.id, role="background"))
        s.commit()

    res = client.delete(f"/api/papers/{pid}")
    assert res.status_code == 204
    assert all(p["id"] != pid for p in client.get("/api/papers").json()["items"])
    with Session(get_engine()) as s:
        assert s.get(Paper, pid).is_deleted is True  # soft delete: row kept
        assert s.exec(select(PaperChunk).where(PaperChunk.paper_id == pid)).all() == []
        assert s.exec(select(PaperConcept).where(PaperConcept.paper_id == pid)).all() == []
        assert s.exec(select(PaperLink).where(PaperLink.paper_id == pid)).all() == []
    # 404 on second delete (already deleted).
    assert client.delete(f"/api/papers/{pid}").status_code == 404


def test_delete_paper_dismisses_related_suggestions(client):
    from app.models import Suggestion

    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    other = client.post(
        "/api/papers/bibtex",
        json={"bibtex": "@article{other, title = {Other Paper}, author = {Carol}, year = {2025}}"},
    ).json()[0]["id"]
    with Session(get_engine()) as s:
        suggestion = Suggestion(
            kind="concept_link",
            title="stale link",
            paper_id=pid,
            related_paper_id=other,
            status="new",
            dedup_key=f"concept_link:{pid}:{other}",
        )
        s.add(suggestion)
        s.commit()
        sid = suggestion.id

    assert client.delete(f"/api/papers/{pid}").status_code == 204

    with Session(get_engine()) as s:
        assert s.get(Suggestion, sid).status == "dismissed"


def test_get_paper_returns_concepts(client):
    from app.models import Concept, PaperConcept

    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    with Session(get_engine()) as s:
        c = Concept(name="transformers", normalized_key="transformers")
        s.add(c)
        s.commit()
        s.refresh(c)
        s.add(PaperConcept(paper_id=pid, concept_id=c.id, weight=1.0))
        s.commit()
    detail = client.get(f"/api/papers/{pid}").json()
    assert detail["concepts"][0]["name"] == "transformers"


def test_reanalyze_reruns_and_returns_summary_and_concepts(client):
    _seed_summary_provider()
    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    # summary + concept extraction both go through ProviderClient.complete.
    calls = {"n": 0}

    def fake_complete(provider, model_id, messages, request_kind, ref_id=None):  # noqa: ANN001
        calls["n"] += 1
        last = messages[-1].get("content") or ""
        # 概念抽取提示词要求返回「JSON 数组」，摘要提示词要求「JSON 对象」——据此区分
        # （两个中文提示词里都可能出现「问题」一词，不能用它区分）。
        is_concepts = "数组" in last
        return CompletionResult(
            content='[{"name":"reanalyzed-concept","type":"method"}]'
            if is_concepts
            else '{"problem":"new","method":"m","dataset":"d","results":"r","limitations":"l"}',
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        )

    with patch("app.providers.client.ProviderClient.complete", side_effect=fake_complete):
        res = client.post(f"/api/papers/{pid}/analyze")
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["problem"] == "new"
    assert any(c["name"] == "reanalyzed-concept" for c in body["concepts"])
    assert calls["n"] >= 2  # summary + concept extraction


def test_reanalyze_requires_provider(client):
    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    assert client.post(f"/api/papers/{pid}/analyze").status_code == 400


def test_reanalyze_404_for_missing(client):
    assert client.post("/api/papers/9999/analyze").status_code == 404


def test_failed_analysis_records_error_and_surfaces_it(client):
    """A failed AI analysis must record WHY and the detail view must show
    status=failed+error, not a silent 'no summary'."""
    _seed_summary_provider()
    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]

    def boom(provider, model_id, messages, request_kind, ref_id=None):  # noqa: ANN001
        raise RuntimeError("upstream returned 500")

    with patch("app.providers.client.ProviderClient.complete", side_effect=boom):
        res = client.post(f"/api/papers/{pid}/analyze")
    assert res.status_code == 200  # analysis failure is recorded, not raised
    detail = client.get(f"/api/papers/{pid}").json()
    assert detail["summary"] is None
    assert detail["analysis"]["status"] == "failed"
    assert "upstream returned 500" in detail["analysis"]["error"]


# ---------------------------------------------------------------- P10.4 citation key 稳定化

def test_generated_citation_key_firstauthor_year_firstword(client):
    # bibtex 条目自带显式 key，形状测试走 manual（无显式 key）路径。
    res = client.post(
        "/api/papers/manual",
        json={
            "title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani", "Noam Shazeer"],
            "year": 2017,
        },
    )
    assert res.status_code == 201
    assert res.json()["citation_key"] == "vaswani2017attention"


def test_generated_citation_key_no_author_uses_anon(client):
    res = client.post("/api/papers/manual", json={"title": "Anonymous Study", "year": 2026})
    assert res.status_code == 201
    assert res.json()["citation_key"] == "anon2026anonymous"


def test_manual_paper_without_key_gets_generated_key(client):
    res = client.post(
        "/api/papers/manual",
        json={"title": "Graph Neural Survey", "authors": ["Alice Zhang"], "year": 2026},
    )
    assert res.status_code == 201
    assert res.json()["citation_key"] == "zhang2026graph"


def test_citation_key_conflict_gets_letter_suffixes(client):
    a = client.post(
        "/api/papers/manual", json={"title": "Deep Retrieval", "authors": ["Jane Smith"], "year": 2025}
    ).json()
    b = client.post(
        "/api/papers/manual",
        json={"title": "Deep Retrieval Again", "authors": ["Jane Smith"], "year": 2025},
    ).json()
    c = client.post(
        "/api/papers/manual",
        json={"title": "Deep Retrieval More", "authors": ["Jane Smith"], "year": 2025},
    ).json()
    assert a["citation_key"] == "smith2025deep"
    assert b["citation_key"] == "smith2025deep-a"
    assert c["citation_key"] == "smith2025deep-b"


def test_arxiv_reingest_keeps_same_citation_key(client, monkeypatch):
    from app.ingestion.sources import FetchedPaper

    def fake_fetch(arxiv_id, client=None):
        return FetchedPaper(
            source="arxiv",
            source_ref=arxiv_id,
            title="Stable Key Paper",
            authors=["Jane Smith"],
            year=2025,
            arxiv_id=arxiv_id,
        )

    monkeypatch.setattr("app.api.papers_api.fetch_arxiv", fake_fetch)
    first = client.post("/api/papers/arxiv", json={"arxiv_id": "2501.00001"}).json()
    second = client.post("/api/papers/arxiv", json={"arxiv_id": "2501.00001"}).json()
    assert second["id"] == first["id"]  # dedup path
    assert first["citation_key"] == "smith2025stable"
    assert second["citation_key"] == first["citation_key"]


def test_base_citekey_unit_rules():
    from app.archive.bibtex import base_citekey
    from app.models import Paper

    p = Paper(source="manual", title="Retrieval Augmented Generation", authors_json='["John R. Smith"]', year=2024)
    assert base_citekey(p) == "smith2024retrieval"

    # articles are skipped for the first title word
    p = Paper(source="manual", title="A Study of Things", authors_json='["Jane Lee"]', year=2023)
    assert base_citekey(p) == "lee2023study"

    # no author → anon (P10.4); Chinese-only authors/titles fall back too
    p = Paper(source="manual", title="Whatever", authors_json="[]")
    assert base_citekey(p) == "anonnodatewhatever"
    p = Paper(source="manual", title="中文标题", authors_json='["张三"]', year=2024)
    assert base_citekey(p) == "anon2024paper"


def test_resolve_unique_citation_key_letter_then_numeric(client):
    from app.ingestion.citation_key import resolve_unique_citation_key

    with Session(get_engine()) as session:
        session.add(Paper(source="manual", title="base", citation_key="key"))
        for ch in "abcdefghijklmnopqrstuvwxyz":
            session.add(Paper(source="manual", title=f"t{ch}", citation_key=f"key-{ch}"))
        session.commit()
        assert resolve_unique_citation_key(session, "key") == "key-27"

        session.add(Paper(source="manual", title="n", citation_key="key-27"))
        session.commit()
        assert resolve_unique_citation_key(session, "key") == "key-28"

        # soft-deleted rows do not block reuse
        victim = session.exec(select(Paper).where(Paper.citation_key == "key-27")).one()
        victim.is_deleted = True
        session.commit()
        assert resolve_unique_citation_key(session, "key") == "key-27"


# ---- T9：服务端全库搜索 ----


def _seed_search_library() -> dict:
    from app.models import Collection, CollectionPaper, Concept, PaperConcept, PaperTag, Tag

    with Session(get_engine()) as session:
        p1 = Paper(
            source="manual",
            citation_key="vaswani2017attention",
            title="Attention Networks Unify Sequences",
            authors_json='["Ashish Vaswani", "Illya Klimt"]',
            year=2017,
            venue="NeurIPS 2017",
            doi="10.5555/attention-doi",
            arxiv_id="1706.03762",
            abstract="We study attention mechanisms for sequence models.",
        )
        p2 = Paper(
            source="manual",
            citation_key="kipf2017gcn",
            title="Graph Convolutional Learning",
            authors_json='["Thomas Kipf"]',
            year=2017,
            venue="ICLR",
            abstract="Semi-supervised classification with graph convolutions.",
        )
        p3 = Paper(
            source="manual",
            title="Deleted Attention Paper",
            abstract="mentions attention but is soft-deleted.",
            is_deleted=True,
        )
        session.add_all([p1, p2, p3])
        session.commit()
        for paper in (p1, p2, p3):
            session.refresh(paper)

        concept = Concept(name="attention-mechanism", normalized_key="attention-mechanism")
        session.add(concept)
        session.commit()
        session.refresh(concept)
        session.add(PaperConcept(paper_id=p1.id, concept_id=concept.id, weight=1.0))

        tag = Tag(name="核心文献", color=None)
        session.add(tag)
        session.commit()
        session.refresh(tag)
        session.add(PaperTag(paper_id=p1.id, tag_id=tag.id))

        collection = Collection(name="必读清单", description=None)
        session.add(collection)
        session.commit()
        session.refresh(collection)
        session.add(CollectionPaper(collection_id=collection.id, paper_id=p1.id))
        session.commit()
        return {"p1": p1.id, "p2": p2.id}


def test_papers_search_matches_each_field_case_insensitively(client):
    ids = _seed_search_library()
    cases = {
        "attention networks": "title",           # 标题（小写匹配大写标题）
        "ATTENTION NETWORKS": "title-case",      # 大写匹配小写查询
        "vaswani2017attention": "citation_key",
        "Vaswani": "authors",
        "neurips": "venue",
        "attention-doi": "doi",
        "1706.03762": "arxiv",
        "sequence models": "abstract",
        "attention-mechanism": "concept",
        "核心文献": "tag",
        "必读清单": "collection",
    }
    for query in cases:
        res = client.get("/api/papers", params={"q": query})
        assert res.status_code == 200, query
        got = [item["id"] for item in res.json()["items"]]
        assert got == [ids["p1"]], f"query={query!r} ({cases[query]}) should match only p1, got {got}"


def test_papers_search_blank_q_matches_plain_listing(client):
    ids = _seed_search_library()
    plain = client.get("/api/papers").json()
    blank = client.get("/api/papers", params={"q": "   "}).json()
    assert blank["total"] == plain["total"] == 2
    assert [i["id"] for i in blank["items"]] == [i["id"] for i in plain["items"]]
    assert ids["p1"] in [i["id"] for i in plain["items"]]


def test_papers_search_paginates_and_reports_filtered_total(client):
    _seed_search_library()
    # 分页 + total：匹配 "2017" 的论文可能不止两篇（其他测试共享库），改用精确词。
    res1 = client.get("/api/papers", params={"q": "attention", "limit": 1})
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["limit"] == 1
    assert len(body1["items"]) == 1
    assert body1["total"] == 1  # 只有 p1 活跃论文命中（软删除排除）

    res2 = client.get("/api/papers", params={"q": "attention", "limit": 1, "offset": 1})
    assert res2.status_code == 200
    assert res2.json()["items"] == []
    assert res2.json()["total"] == 1


def test_papers_search_excludes_soft_deleted_and_keeps_id_desc_order(client):
    # 单独种 3 篇可命中的论文，验证排序 id DESC 与软删除排除。
    with Session(get_engine()) as session:
        created = []
        for i in range(3):
            p = Paper(source="manual", title=f"排序验证 attention {i}", abstract="probe-xyzzy")
            session.add(p)
            session.commit()
            session.refresh(p)
            created.append(p.id)
        victim = session.get(Paper, created[1])
        victim.is_deleted = True
        session.commit()

    res = client.get("/api/papers", params={"q": "probe-xyzzy"})
    assert res.status_code == 200
    got = [item["id"] for item in res.json()["items"]]
    assert got == sorted([created[0], created[2]], reverse=True)
    assert created[1] not in got


def test_papers_search_requires_all_terms_to_match(client):
    ids = _seed_search_library()
    res = client.get("/api/papers", params={"q": "attention graph"})
    assert res.status_code == 200
    # 多词按 AND：没有任何一篇同时含 attention 和 graph。
    assert [item["id"] for item in res.json()["items"]] == []
    assert ids["p1"] is not None


def test_papers_list_returns_created_at(client):
    _seed_search_library()
    res = client.get("/api/papers", params={"q": "attention networks"})
    item = res.json()["items"][0]
    assert "created_at" in item and item["created_at"]


# ---- T10：库外论文一键加入待读 ----


def _queue_payload(**overrides):
    payload = {
        "title": "External Queued Paper",
        "doi": "10.9999/queued",
        "arxiv_id": None,
        "year": 2025,
        "venue": "Test Venue",
        "authors": ["Queue Author"],
    }
    payload.update(overrides)
    return payload


def test_add_external_paper_by_title_creates_and_queues(client):
    res = client.post("/api/papers/from-external", json=_queue_payload(arxiv_id=None, doi=None))
    assert res.status_code == 201
    body = res.json()
    assert body["created"] is True
    assert body["paper"]["title"] == "External Queued Paper"
    assert body["paper"]["source"] == "manual"

    reading = client.get(f"/api/papers/{body['paper']['id']}/reading").json()
    assert reading["state"]["status"] == "queued"


def test_add_external_paper_prefers_arxiv_source(client):
    from app.ingestion.sources import FetchedPaper

    fetched = FetchedPaper(
        source="arxiv",
        title="ArXiv Queued Paper",
        authors=["ArXiv Author"],
        abstract="Abstract from arXiv.",
        year=2024,
        arxiv_id="2401.99999",
        doi="10.9999/arxiv",
    )
    with patch("app.api.papers_api.fetch_arxiv", return_value=fetched):
        res = client.post("/api/papers/from-external", json=_queue_payload(arxiv_id="2401.99999"))
    assert res.status_code == 201
    body = res.json()
    assert body["created"] is True
    assert body["paper"]["source"] == "arxiv"
    assert body["paper"]["arxiv_id"] == "2401.99999"

    reading = client.get(f"/api/papers/{body['paper']['id']}/reading").json()
    assert reading["state"]["status"] == "queued"


def test_add_external_paper_arxiv_failure_falls_back_to_manual(client):
    with patch("app.api.papers_api.fetch_arxiv", side_effect=RuntimeError("network down")):
        res = client.post(
            "/api/papers/from-external",
            json=_queue_payload(title="Fallback Paper", arxiv_id="2402.00001", doi=None),
        )
    assert res.status_code == 201
    body = res.json()
    assert body["created"] is True
    assert body["paper"]["source"] == "manual"
    assert body["paper"]["arxiv_id"] == "2402.00001"
    assert body["paper"]["title"] == "Fallback Paper"


def test_add_external_paper_arxiv_failure_without_title_is_502(client):
    with patch("app.api.papers_api.fetch_arxiv", side_effect=RuntimeError("network down")):
        res = client.post(
            "/api/papers/from-external",
            json={"arxiv_id": "2403.00001"},
        )
    assert res.status_code == 502


def test_add_external_paper_duplicate_is_idempotent_success(client):
    first = client.post("/api/papers/from-external", json=_queue_payload())
    assert first.status_code == 201
    first_id = first.json()["paper"]["id"]

    second = client.post("/api/papers/from-external", json=_queue_payload())
    assert second.status_code == 201  # 幂等成功，不暴露重复错误
    body = second.json()
    assert body["created"] is False
    assert body["paper"]["id"] == first_id

    # 重复 DOI/标题也命中同一篇
    third = client.post(
        "/api/papers/from-external",
        json={"title": "external queued paper", "doi": "10.9999/queued"},
    )
    assert third.status_code == 201
    assert third.json()["paper"]["id"] == first_id


def test_add_external_paper_rejects_insufficient_metadata(client):
    assert client.post("/api/papers/from-external", json={}).status_code == 422
    assert client.post("/api/papers/from-external", json={"year": 2020}).status_code == 422
    # 仅有 DOI、无标题且无 arXiv：无法构造论文记录。
    assert client.post("/api/papers/from-external", json={"doi": "10.1/only-doi"}).status_code == 422


def test_add_external_paper_keeps_advanced_reading_state(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Already Read Paper", authors_json="[]")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        pid = paper.id
        from app.models import PaperReadingState

        session.add(PaperReadingState(paper_id=pid, status="read"))
        session.commit()

    res = client.post("/api/papers/from-external", json={"title": "Already Read Paper"})
    assert res.status_code == 201
    assert res.json()["created"] is False
    reading = client.get(f"/api/papers/{pid}/reading").json()
    assert reading["state"]["status"] == "read"  # 不把已读论文拉回待读
