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
            "title": "  面向硕士论文的中文知识图谱综述  ",
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
    assert body["title"] == "面向硕士论文的中文知识图谱综述"
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
    assert client.get(f"/api/papers/{second_id}").json()["citation_key"] is None


def test_bibtex_ingest_does_not_store_invalid_citation_key(client):
    bibtex = "@article{bad$key, title = {Invalid Key Paper}, author = {Ada}, year = {2024}}"

    res = client.post("/api/papers/bibtex", json={"bibtex": bibtex})

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    detail = client.get(f"/api/papers/{body[0]['id']}").json()
    assert detail["title"] == "Invalid Key Paper"
    assert detail["citation_key"] is None


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
    assert len(client.get("/api/papers").json()) == 1


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
    visible = client.get("/api/papers").json()
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
    visible = client.get("/api/papers").json()
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
    row = next(item for item in res.json() if item["id"] == pid)
    assert row["authors"] == []


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
    row = next(item for item in listed.json() if item["id"] == pid)
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


def test_related_papers_degrades_on_network_error(client):
    """OpenAlex must never break the UI — a dead network returns []."""
    pid = client.post("/api/papers/bibtex", json={"bibtex": BIBTEX}).json()[0]["id"]
    with patch("app.knowledge.recommend.httpx.get", side_effect=httpx.ConnectError("offline")):
        res = client.get(f"/api/papers/{pid}/related")
    assert res.status_code == 200
    assert res.json() == []


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
    assert all(p["id"] != pid for p in client.get("/api/papers").json())
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
