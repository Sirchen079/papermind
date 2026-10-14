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
    # W01 收紧契约：body 候选必须过题名核验，正文自带检索命中的题名作自身声明。
    raw = make_pdf("Verified Title\nIntro. doi:10.1038/s41586-019-1234-5")
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
    # W01：正文含自身题名以满足 body 候选的题名核验（契约收紧，非放宽）。
    raw = make_pdf("Verified Title\nIntro. doi:10.1038/s41586-019-1234-5")
    first = upload(client, raw, "a.pdf").json()
    second = upload(client, raw, "b.pdf")
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert total_papers(client) == 1


def test_same_doi_different_bytes_keeps_stored_pdf(client, monkeypatch):
    mock_crossref(monkeypatch, "10.1038/merge")
    # W01：正文含自身题名以满足 body 候选的题名核验（契约收紧，非放宽）。
    first_raw = make_pdf("Verified Title\nStudy body A. doi:10.1038/merge")
    first = upload(client, first_raw, "a.pdf").json()
    second = upload(client, make_pdf("Verified Title\nExpanded study body B. doi:10.1038/merge"), "b.pdf")
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
    # W01：正文含自身题名以满足 body 候选的题名核验（契约收紧，非放宽）。
    res = upload(client, make_pdf("Verified Title\nBody. doi:10.1038/keepme"), "file.pdf")
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
    # W01/F02 契约收紧：查询失败时未确认 DOI 不写入记录、不参与去重，
    # 条目独立保存并标记身份未确认（旧断言 doi=='10.1038/slow' 固化的是缺陷行为）。
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
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
    # W01：正文含自身题名以满足 body 候选的题名核验（契约收紧，非放宽）。
    first = upload(client, make_pdf("Arxiv Title\narXiv:2508.17122v7"), "one.pdf").json()
    assert first["arxiv_id"] == "2508.17122v7"
    assert first["title"] == "Arxiv Title"
    assert first["identity"]["source"] == "arxiv" and first["identity"]["status"] == "retrieved"
    second = upload(client, make_pdf("Arxiv Title\narXiv:2508.17122v7 with extra body"), "two.pdf")
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
    # W01 契约收紧：body 候选须过题名核验，故被引 PDF 正文带自身题名；
    # 断言不变（被引记录字节保留、新文档独立、共 2 条）。
    cited_pdf = make_pdf("Cited Earlier Work\nBody. doi:10.1234/cited-paper")
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


# --- W01（F01/F02 二次返工）：完整参考文献条目与查询失败路径 ------------------

INDEPENDENT_PAGES = [
    ["Actual Independent New Study", "This is our own different research."],
]


def test_full_reference_entry_with_cited_title_does_not_self_identify(client, monkeypatch):
    # F01 主反例：完整参考文献条目（含被引题名+DOI）不能自证上传文档身份；
    # 被引论文的标题、标识与 PDF 关联必须完全不变，新文档独立可访问。
    cited = client.post("/api/papers/bibtex", json={"bibtex": CITED_BIBTEX}).json()[0]
    mock_crossref_map(monkeypatch, {
        "10.1234/ref-present": {"title": "Cited Earlier Work", "year": 2019},
    })
    raw = make_pages_pdf(INDEPENDENT_PAGES + [
        ["References", "A. Author. Cited Earlier Work. doi:10.1234/ref-present"],
    ])
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != cited["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unconfirmed"
    assert body["identity"]["reason"] == "unverified_title"
    assert body["has_pdf"] is True
    assert total_papers(client) == 2
    cited_now = get_paper(client, cited["id"])
    assert cited_now["title"] == "Cited Earlier Work"
    assert cited_now["doi"] == "10.1234/cited-paper"
    assert cited_now["has_pdf"] is False
    with Session(get_engine()) as session:
        fresh = session.get(Paper, body["id"])
        assert fresh.doi is None
        assert Path(fresh.pdf_path).read_bytes() == raw


def test_body_citation_doi_is_not_self_identity_without_title_evidence(client, monkeypatch):
    # F01 附带反例：正文中单个被引 DOI（即便带 doi: 标签）不是文档自身身份，
    # 不能因“唯一候选”直接归并到库中已有论文。
    existing = client.post("/api/papers/bibtex", json={"bibtex": (
        "@article{cited, title={Compared Baseline Method}, author={B. Beta}, "
        "year={2020}, doi={10.1234/body-citation}}")}).json()[0]
    mock_crossref_map(monkeypatch, {
        "10.1234/body-citation": {"title": "Compared Baseline Method", "year": 2020},
    })
    raw = make_pdf("We compare with doi:10.1234/body-citation and propose our method.")
    res = upload(client, raw, "ours.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != existing["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert total_papers(client) == 2
    assert get_paper(client, existing["id"])["has_pdf"] is False
    with Session(get_engine()) as session:
        assert Path(session.get(Paper, body["id"]).pdf_path).read_bytes() == raw


def _mock_crossref_timeout(monkeypatch):
    def timeout(identifier):
        raise TimeoutError("crossref down")
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref", timeout)


def test_crossref_timeout_saves_independent_unconfirmed_without_doi(client, monkeypatch):
    # F02：查询超时后未确认标识不得下沉到去重；库中被引论文原样保留。
    cited = client.post("/api/papers/bibtex", json={"bibtex": CITED_BIBTEX}).json()[0]
    _mock_crossref_timeout(monkeypatch)
    raw = make_pages_pdf(INDEPENDENT_PAGES + [
        ["References", "A. Author. Cited Earlier Work. doi:10.1234/cited-paper"],
    ])
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != cited["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unavailable"
    assert body["identity"]["error_type"] == "TimeoutError"
    assert total_papers(client) == 2
    assert get_paper(client, cited["id"])["has_pdf"] is False
    with Session(get_engine()) as session:
        assert Path(session.get(Paper, body["id"]).pdf_path).read_bytes() == raw


def test_crossref_none_result_never_merges(client, monkeypatch):
    # F02 None 分支：查询返回 None（无可用元数据）时标识同样必须隔离。
    cited = client.post("/api/papers/bibtex", json={"bibtex": CITED_BIBTEX}).json()[0]
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref", lambda identifier: None)
    raw = make_pages_pdf(INDEPENDENT_PAGES + [
        ["References", "A. Author. Cited Earlier Work. doi:10.1234/cited-paper"],
    ])
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != cited["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert total_papers(client) == 2
    assert get_paper(client, cited["id"])["has_pdf"] is False


def test_unexpected_lookup_exception_saves_independent(client, monkeypatch):
    # F02 异常分支：校验层内部异常同样不得把候选标识用于自动归并。
    cited = client.post("/api/papers/bibtex", json={"bibtex": CITED_BIBTEX}).json()[0]
    def boom(doi):
        raise RuntimeError("unexpected verification failure")
    monkeypatch.setattr("app.ingestion.sources.lookup_doi_metadata", boom)
    raw = make_pages_pdf(INDEPENDENT_PAGES + [
        ["References", "A. Author. Cited Earlier Work. doi:10.1234/cited-paper"],
    ])
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != cited["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unavailable"
    assert body["identity"]["error_type"] == "RuntimeError"
    assert total_papers(client) == 2
    assert get_paper(client, cited["id"])["has_pdf"] is False


def test_timeout_with_cited_pdf_present_keeps_existing_bytes(client, monkeypatch):
    # F02：库中被引论文已有 PDF 时，其字节不变；新文档独立保存不丢弃。
    # 先用成功 mock 让被引 PDF 合法并入被引记录，再切换超时 mock 上传新文档
    #（W01 契约：body 候选须过题名核验，故 PDF 正文带自身题名）。
    client.post("/api/papers/bibtex", json={"bibtex": CITED_BIBTEX})
    mock_crossref_map(monkeypatch, {
        "10.1234/cited-paper": {"title": "Cited Earlier Work", "year": 2019},
    })
    cited_pdf = make_pdf("Cited Earlier Work\nBody. doi:10.1234/cited-paper")
    first = upload(client, cited_pdf, "cited.pdf").json()
    _mock_crossref_timeout(monkeypatch)
    raw = make_pages_pdf(INDEPENDENT_PAGES + [
        ["References", "A. Author. Cited Earlier Work. doi:10.1234/cited-paper"],
    ])
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != first["id"]
    assert body["identity_status"] == "unconfirmed"
    assert total_papers(client) == 2
    with Session(get_engine()) as session:
        kept = Path(session.get(Paper, first["id"]).pdf_path).read_bytes()
    assert kept == cited_pdf


def test_arxiv_timeout_with_reference_only_id_saves_independent(client, monkeypatch):
    # F02/F01 arXiv 分支：参考文献节内的 arXiv id 查询失败时同样不得归并。
    old = client.post("/api/papers/manual", json={
        "title": "Attention Old Work", "arxiv_id": "1706.03762"}).json()
    def timeout(arxiv_id):
        raise TimeoutError("arxiv down")
    monkeypatch.setattr("app.ingestion.sources.fetch_arxiv_metadata", timeout)
    raw = make_pages_pdf([
        ["Some study text without identifiers in the body."],
        ["References", "D. Dao. Attention Old Work. arXiv:1706.03762"],
    ])
    res = upload(client, raw, "ext.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != old["id"]
    assert body["arxiv_id"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unavailable"
    assert total_papers(client) == 2
    assert get_paper(client, old["id"])["has_pdf"] is False


# --- W01 正当路径回归：自身声明明确的正常导入不被降级 -------------------------

def test_metadata_title_match_confirms_identity_and_merges(client, monkeypatch):
    # 元数据 title 与检索题名一致即自身声明：正常确认合并，不标未确认。
    mock_crossref(monkeypatch, "10.1038/own-work")
    raw = make_pdf("Body without the title printed. doi:10.1038/own-work",
                   meta={"title": "Verified Title"})
    res = upload(client, raw, "own.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Verified Title"
    assert body["doi"] == "10.1038/own-work"
    assert body["identity"]["status"] == "retrieved"
    assert body["identity_status"] is None


def test_metadata_doi_with_matching_title_merges(client, monkeypatch):
    # 元数据 subject 携带自身 DOI + 元数据题名一致：正常确认合并。
    mock_crossref(monkeypatch, "10.1038/meta-doi")
    raw = make_pdf("No identifiers printed in the body.", meta={
        "title": "Verified Title", "subject": "doi:10.1038/meta-doi"})
    res = upload(client, raw, "meta.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Verified Title"
    assert body["doi"] == "10.1038/meta-doi"
    assert body["identity"]["status"] == "retrieved"
    assert body["identity_status"] is None


def test_unconfirmed_upload_same_bytes_still_dedups(client, monkeypatch):
    # 字节相同文件的合法去重不受未确认身份影响：重复上传不产生第二条记录。
    _mock_crossref_timeout(monkeypatch)
    raw = make_pdf("Intro. doi:10.1038/slow-repeat")
    first = upload(client, raw, "a.pdf").json()
    second = upload(client, raw, "b.pdf")
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert total_papers(client) == 1


# --- 正文提及被引题名+DOI 不得自证身份、不得误挂 PDF -------------------------

BASELINE_BIBTEX = ("@article{baseline, title={Established Baseline Work}, "
                   "author={B. Beta}, year={2018}, doi={10.1234/body-title}}")
RELATED_BIBTEX = ("@article{related, title={Related Earlier Study}, "
                  "author={R. Researcher}, year={2017}, doi={10.1234/body-ref}}")

INTRO_MENTION_PAGES = [
    ["Actual Independent New Study", "Introduction",
     "We compare against Established Baseline Work (doi:10.1234/body-title).",
     "Our contribution is a different method."],
]


def test_intro_cited_title_and_doi_saves_independent_unconfirmed(client, monkeypatch):
    # 正文提及被引题名+DOI（无 metadata title，mock Crossref）：
    # 新 PDF 不得挂到被引记录下，旧记录与磁盘字节保持不变。
    baseline = client.post("/api/papers/bibtex", json={"bibtex": BASELINE_BIBTEX}).json()[0]
    mock_crossref_map(monkeypatch, {
        "10.1234/body-title": {"title": "Established Baseline Work", "year": 2018},
    })
    raw = make_pages_pdf(INTRO_MENTION_PAGES)
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != baseline["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unconfirmed"
    assert body["identity"]["reason"] == "unverified_title"
    assert total_papers(client) == 2
    baseline_now = get_paper(client, baseline["id"])
    assert baseline_now["title"] == "Established Baseline Work"
    assert baseline_now["doi"] == "10.1234/body-title"
    assert baseline_now["has_pdf"] is False
    with Session(get_engine()) as session:
        fresh = session.get(Paper, body["id"])
        assert fresh.doi is None
        assert Path(fresh.pdf_path).read_bytes() == raw


def test_reference_doi_with_body_mention_saves_independent_unconfirmed(client, monkeypatch):
    # 正文句提及被引题名、DOI 印在参考文献节（mock Crossref）：
    # 新文档独立保存 unconfirmed，被引记录原样不动。
    related = client.post("/api/papers/bibtex", json={"bibtex": RELATED_BIBTEX}).json()[0]
    mock_crossref_map(monkeypatch, {
        "10.1234/body-ref": {"title": "Related Earlier Study", "year": 2017},
    })
    raw = make_pages_pdf([
        ["Actual Independent New Study", "Introduction",
         "We extend Related Earlier Study with a new dataset."],
        ["References", "A. Author. Related Earlier Study. doi:10.1234/body-ref"],
    ])
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != related["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unconfirmed"
    assert body["identity"]["reason"] == "unverified_title"
    assert total_papers(client) == 2
    related_now = get_paper(client, related["id"])
    assert related_now["title"] == "Related Earlier Study"
    assert related_now["doi"] == "10.1234/body-ref"
    assert related_now["has_pdf"] is False
    with Session(get_engine()) as session:
        fresh = session.get(Paper, body["id"])
        assert fresh.doi is None
        assert Path(fresh.pdf_path).read_bytes() == raw


def test_intro_cited_title_does_not_attach_to_record_with_pdf(client, monkeypatch):
    # 已有 PDF 的被引记录保护：正文提及其题名+DOI 的新文档不得并入，
    # 被引记录的 PDF 字节保持不动，新文档独立保存。
    client.post("/api/papers/bibtex", json={"bibtex": BASELINE_BIBTEX})
    mock_crossref_map(monkeypatch, {
        "10.1234/body-title": {"title": "Established Baseline Work", "year": 2018},
    })
    cited_pdf = make_pdf("Established Baseline Work\nBody. doi:10.1234/body-title")
    first = upload(client, cited_pdf, "baseline.pdf").json()
    assert first["has_pdf"] is True
    raw = make_pages_pdf(INTRO_MENTION_PAGES)
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != first["id"]
    assert body["identity_status"] == "unconfirmed"
    assert total_papers(client) == 2
    with Session(get_engine()) as session:
        kept = Path(session.get(Paper, first["id"]).pdf_path).read_bytes()
    assert kept == cited_pdf


def test_head_standalone_cited_title_line_saves_independent_unconfirmed(client, monkeypatch):
    # 被引题名单独成行、位于首页头部第 3 行，仍只是文献提及；
    # 自身题名只认首个非空内容行起的完整前缀，正文开始后不能跳行匹配。
    related = client.post("/api/papers/bibtex", json={"bibtex": RELATED_BIBTEX}).json()[0]
    mock_crossref_map(monkeypatch, {
        "10.1234/body-ref": {"title": "Related Earlier Study", "year": 2017},
    })
    raw = make_pages_pdf([
        ["Actual New Study", "Introduction", "Related Earlier Study",
         "We extend this work with a new dataset. doi:10.1234/body-ref"],
    ])
    res = upload(client, raw, "independent.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != related["id"]
    assert body["doi"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unconfirmed"
    assert body["identity"]["reason"] == "unverified_title"
    assert total_papers(client) == 2
    assert get_paper(client, related["id"])["has_pdf"] is False
    with Session(get_engine()) as session:
        assert Path(session.get(Paper, body["id"]).pdf_path).read_bytes() == raw


def test_metadata_doi_with_cited_arxiv_hit_saves_independent_unconfirmed(client, monkeypatch):
    # 查询命中的是正文被引 arXiv id（body 来源）：即使 metadata subject 携带
    # 另一个 DOI，也必须过标题核验，不得把上传挂到被引 arXiv 记录下。
    old = client.post("/api/papers/manual", json={
        "title": "Attention Old Work", "arxiv_id": "1706.03762"}).json()
    def cited_hit(arxiv_id):
        return FetchedPaper(source="arxiv", source_ref=arxiv_id,
                            title="Attention Old Work", authors=["D. Dao"],
                            arxiv_id=arxiv_id), {
            "status": "retrieved", "source": "arxiv", "identifier": arxiv_id}
    monkeypatch.setattr("app.ingestion.sources.fetch_arxiv_metadata", cited_hit)
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref",
                        lambda doi: pytest.fail("crossref must not run when arXiv verified"))
    raw = make_pdf("Actual Independent New Study\nIntroduction\n"
                   "We build on arXiv:1706.03762.",
                   meta={"subject": "doi:10.1234/meta"})
    res = upload(client, raw, "ours.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != old["id"]
    assert body["doi"] is None
    assert body["arxiv_id"] is None
    assert body["identity_status"] == "unconfirmed"
    assert body["identity"]["status"] == "unconfirmed"
    assert body["identity"]["reason"] == "unverified_title"
    assert total_papers(client) == 2
    assert get_paper(client, old["id"])["has_pdf"] is False
    with Session(get_engine()) as session:
        assert Path(session.get(Paper, body["id"]).pdf_path).read_bytes() == raw


def test_metadata_doi_query_confirms_despite_cited_arxiv_outage(client, monkeypatch):
    # 查询成功的是 metadata 来源 DOI：其自身声明成立，不被另一个查询失败的
    # 正文被引 arXiv 候选拖入未确认；被引 arXiv id 也不得随行写入。
    record = client.post("/api/papers/bibtex", json={"bibtex": (
        "@article{meta, title={Metadata Declared Work}, author={M. Meta}, "
        "year={2021}, doi={10.1234/meta}}")}).json()[0]
    def outage(arxiv_id):
        return None, {"status": "unavailable", "source": "arxiv",
                      "identifier": arxiv_id, "error_type": "TimeoutError"}
    monkeypatch.setattr("app.ingestion.sources.fetch_arxiv_metadata", outage)
    mock_crossref_map(monkeypatch, {
        "10.1234/meta": {"title": "Metadata Declared Work", "year": 2021},
    })
    raw = make_pdf("Actual Independent New Study\nIntroduction\n"
                   "We build on arXiv:1706.03762.",
                   meta={"subject": "doi:10.1234/meta"})
    res = upload(client, raw, "ours.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == record["id"]
    assert body["title"] == "Metadata Declared Work"
    assert body["doi"] == "10.1234/meta"
    assert body["arxiv_id"] is None
    assert body["identity"]["status"] == "retrieved"
    assert body["identity"]["source"] == "crossref"
    assert body["identity_status"] is None
    assert total_papers(client) == 1


def test_arxiv_confirmation_does_not_publish_unverified_body_doi(client, monkeypatch):
    # 标识边界：arXiv 自身声明确认后，正文里被引论文的 DOI 不得随行写入记录、
    # 参与去重把上传挂到被引论文下；只有检索记录自身携带的标识可发布。
    cited = client.post("/api/papers/bibtex", json={"bibtex": (
        "@article{cited, title={Cited Earlier Work}, author={C. Cited}, "
        "year={2019}, doi={10.1234/cited-doi}}")}).json()[0]
    def fetch_arxiv(arxiv_id, client=None, download_pdf=True):
        assert not download_pdf
        return FetchedPaper(source="arxiv", source_ref=arxiv_id,
                            title="Actual New Paper", authors=["A. Author"],
                            arxiv_id=arxiv_id)
    monkeypatch.setattr("app.ingestion.sources.fetch_arxiv", fetch_arxiv)
    monkeypatch.setattr("app.ingestion.sources.fetch_crossref",
                        lambda doi: pytest.fail("crossref must not run when arXiv verified"))
    raw = make_pages_pdf([
        ["Actual New Paper", "We build on doi:10.1234/cited-doi.",
         "arXiv:2601.00001v1"],
    ])
    res = upload(client, raw, "mixed.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != cited["id"]
    assert body["title"] == "Actual New Paper"
    assert body["arxiv_id"] == "2601.00001v1"
    assert body["doi"] is None
    assert body["identity"]["status"] == "retrieved"
    assert get_paper(client, cited["id"])["has_pdf"] is False
    assert total_papers(client) == 2
