"""PaperCitation model, soft-delete cascade, and extraction tests (P8.1/P8.2)."""

from io import BytesIO

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Paper, PaperCitation


def _paper(session: Session, title: str) -> Paper:
    paper = Paper(source="manual", title=title)
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def test_papercitation_unique_source_and_title_norm(client):
    with Session(get_engine()) as session:
        source = _paper(session, "Citing Paper")
        first = PaperCitation(
            source_paper_id=source.id,
            raw_ref="[1] Some Author. A cited work. 2023.",
            ref_title="A cited work",
            ref_title_norm="a cited work",
        )
        session.add(first)
        session.commit()

        duplicate = PaperCitation(
            source_paper_id=source.id,
            raw_ref="[1] Some Author. A cited work (duplicate). 2023.",
            ref_title="A cited work",
            ref_title_norm="a cited work",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Same title under a different source paper is fine.
        other_source = _paper(session, "Another Citing Paper")
        session.add(
            PaperCitation(
                source_paper_id=other_source.id,
                raw_ref="[7] Some Author. A cited work. 2023.",
                ref_title="A cited work",
                ref_title_norm="a cited work",
            )
        )
        session.commit()


def test_papercitation_allows_multiple_null_title_norm(client):
    # SQLite unique indexes treat NULL as distinct: raw refs without a parsed
    # title must not collide.
    with Session(get_engine()) as session:
        source = _paper(session, "Citing Paper")
        session.add(PaperCitation(source_paper_id=source.id, raw_ref="opaque ref one"))
        session.add(PaperCitation(source_paper_id=source.id, raw_ref="opaque ref two"))
        session.commit()

        rows = session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == source.id)
        ).all()
        assert len(rows) == 2


def test_delete_paper_cascades_citations(client):
    with Session(get_engine()) as session:
        source = _paper(session, "Citing Paper")
        _paper(session, "Cited Paper")
        session.add(
            PaperCitation(
                source_paper_id=source.id,
                raw_ref="[1] Some Author. A cited work. 2023.",
                ref_title="A cited work",
                ref_title_norm="a cited work",
            )
        )
        session.commit()
        source_id = source.id

    # Soft-deleting the source removes its bibliography rows entirely.
    assert client.delete(f"/api/papers/{source_id}").status_code == 204
    with Session(get_engine()) as session:
        assert session.exec(select(PaperCitation)).all() == []


def test_delete_paper_degrades_incoming_matches_to_unmatched(client):
    with Session(get_engine()) as session:
        source = _paper(session, "Citing Paper")
        target = _paper(session, "Cited Paper")
        session.add(
            PaperCitation(
                source_paper_id=source.id,
                target_paper_id=target.id,
                raw_ref="[1] Cited Paper Author. Cited Paper. 2023.",
                ref_title="Cited Paper",
                ref_title_norm="cited paper",
                match_status="matched",
                match_confidence=0.9,
            )
        )
        session.commit()
        source_id, target_id = source.id, target.id

    # Soft-delete the TARGET: the citing paper keeps the raw reference,
    # degrading to unmatched for a future re-match.
    assert client.delete(f"/api/papers/{target_id}").status_code == 204
    with Session(get_engine()) as session:
        row = session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == source_id)
        ).one()
        assert row.target_paper_id is None
        assert row.match_status == "unmatched"
        assert row.match_confidence is None
        assert row.raw_ref.startswith("[1]")


# ---------------------------------------------------------------------------
# P8.2 — reference extraction (rule-first, LLM fallback)
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock

from app.ingestion.citation_extract import (
    extract_and_store_citations,
    extract_citations,
    extract_references_section,
    parse_reference,
    split_references,
)

NUMBERED_FULL_TEXT = """A Study of Graph Learning

We study graphs. See the cited works below for details.

References
[1] Smith, J., and Doe, A. Attention is all you need. In Advances in Neural
Information Processing Systems (2017), pp. 5998-6008.
[2] Zhang, Y. et al. A study of graph networks. arXiv:2301.12345, 2023.
[3] Brown, T. Language models are few-shot learners. doi:10.5555/fewshot. 2020.
"""


def test_extract_references_section_takes_last_and_cuts_appendix():
    text = "Introduction mentions References\n...\nReferences\n[1] one.\n[2] two.\n\nAppendix A\nextra"
    section = extract_references_section(text)
    assert section is not None
    assert "[1] one." in section
    assert "[2] two." in section
    assert "Appendix" not in section
    assert extract_references_section("no section here") is None


def test_split_references_numbered_entries_rejoin_wrapped_lines():
    section = extract_references_section(NUMBERED_FULL_TEXT)
    entries = split_references(section)
    assert len(entries) == 3
    assert entries[0].startswith("[1]")
    assert "Information Processing Systems" in entries[0]  # wrapped line rejoined
    assert entries[1].startswith("[2]")
    assert entries[2].startswith("[3]")


def test_parse_reference_extracts_fields():
    parsed = parse_reference(
        "[2] Zhang, Y. et al. A study of graph networks. arXiv:2301.12345, 2023."
    )
    assert parsed["title"] == "A study of graph networks"
    assert parsed["arxiv_id"] == "2301.12345"
    assert parsed["year"] == 2023
    assert parsed.get("doi") is None

    parsed_doi = parse_reference(
        "[3] Brown, T. Language models are few-shot learners. doi:10.5555/fewshot. 2020."
    )
    assert parsed_doi["title"] == "Language models are few-shot learners"
    assert parsed_doi["doi"] == "10.5555/fewshot"
    assert parsed_doi["year"] == 2020

    parsed_venue = parse_reference(
        "[1] Smith, J., and Doe, A. Attention is all you need. "
        "In Advances in Neural Information Processing Systems (2017), pp. 5998-6008."
    )
    assert parsed_venue["title"] == "Attention is all you need"
    assert parsed_venue["year"] == 2017


def test_extract_citations_rule_based_enough_entries_skips_llm():
    client = MagicMock()
    refs = extract_citations(NUMBERED_FULL_TEXT, client, MagicMock(), "gpt-4o")
    assert len(refs) == 3
    titles = {r["title"] for r in refs}
    assert "A study of graph networks" in titles
    client.complete.assert_not_called()


def test_extract_citations_llm_fallback_and_merge():
    # Only one ruled entry has a title (< 3) and the section is long enough:
    # the LLM must be consulted, its entries preferred, ruled-only titles kept.
    sparse = (
        "References\n"
        "[1] Alpha, B. Some ruled title here. arXiv:2302.00001, 2023.\n" + "filler line for section length\n" * 20
    )
    llm_payload = (
        '[{"raw_ref": "[9] LLM, A. An LLM-parsed work. 2024.", "title": "An LLM-parsed work", '
        '"doi": "", "arxiv_id": "2409.00001", "year": 2024, "authors": ["LLM, A"]}]'
    )
    client = MagicMock()
    client.complete.return_value = MagicMock(content=llm_payload)

    refs = extract_citations(sparse, client, MagicMock(), "gpt-4o")

    client.complete.assert_called_once()
    by_title = {r["title"]: r for r in refs}
    assert "An LLM-parsed work" in by_title
    assert by_title["An LLM-parsed work"]["arxiv_id"] == "2409.00001"
    assert "Some ruled title here" in by_title  # ruled entry kept after merge


def test_extract_citations_llm_failure_degrades_to_ruled():
    sparse = (
        "References\n[1] Alpha, B. Some ruled title here. arXiv:2302.00001, 2023.\n"
        + "filler line for section length\n" * 20
    )
    client = MagicMock()
    client.complete.side_effect = RuntimeError("provider down")

    refs = extract_citations(sparse, client, MagicMock(), "gpt-4o")

    assert refs  # raw entries survive
    assert any(r.get("title") == "Some ruled title here" for r in refs)


def test_store_citations_idempotent_on_reextraction(client):
    with Session(get_engine()) as session:
        source = _paper(session, "Citing Paper")
        source.full_text = NUMBERED_FULL_TEXT
        session.add(source)
        session.commit()

        first = extract_and_store_citations(session, source)
        assert first == 3
        rows = session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == source.id)
        ).all()
        assert len(rows) == 3
        by_norm = {r.ref_title_norm: r for r in rows}
        assert "a study of graph networks" in by_norm
        assert by_norm["a study of graph networks"].ref_arxiv_id == "2301.12345"
        assert by_norm["attention is all you need"].ref_year == 2017

        # Re-running extraction must not insert duplicates.
        assert extract_and_store_citations(session, source) == 0
        assert (
            len(
                session.exec(
                    select(PaperCitation).where(PaperCitation.source_paper_id == source.id)
                ).all()
            )
            == 3
        )


def test_pdf_ingest_extracts_citations_end_to_end(client):
    """Full ingest path: PDF upload → parse → rule-based extraction, no LLM."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A test paper body before the references.\n\nReferences\n")
    page.insert_text(
        (72, 110),
        "[1] Smith, J., and Doe, A. Attention is all you need. In Advances in "
        "Neural Information Processing Systems (2017), pp. 5998-6008.\n"
        "[2] Zhang, Y. et al. A study of graph networks. arXiv:2301.12345, 2023.\n"
        "[3] Brown, T. Language models are few-shot learners. doi:10.5555/fewshot. 2020.\n",
    )
    buf = BytesIO()
    doc.save(buf)
    doc.close()

    res = client.post(
        "/api/papers/pdf",
        files={"file": ("cited.pdf", buf.getvalue(), "application/pdf")},
    )
    assert res.status_code == 200
    pid = res.json()["id"]

    with Session(get_engine()) as session:
        rows = session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == pid)
        ).all()
        norms = {r.ref_title_norm for r in rows}
        assert len(rows) >= 2  # parse fidelity varies; core entries must survive
        assert "a study of graph networks" in norms


# ---------------------------------------------------------------------------
# P8.3 — matching & bidirectional backfill
# ---------------------------------------------------------------------------

from app.ingestion.citation_match import match_citations_for_paper
from app.ingestion.dedup import normalize_title


def _citing_paper_with_refs(session, title, refs):
    paper = _paper(session, title)
    for ref in refs:
        session.add(
            PaperCitation(
                source_paper_id=paper.id,
                raw_ref=ref.get("raw_ref", ""),
                ref_title=ref.get("title"),
                ref_title_norm=normalize_title(ref.get("title")) or None,
                ref_doi=ref.get("doi"),
                ref_arxiv_id=ref.get("arxiv_id"),
                ref_year=ref.get("year"),
            )
        )
    session.commit()
    session.refresh(paper)
    return paper


def test_forward_match_cited_paper_already_in_library(client):
    with Session(get_engine()) as session:
        target = _paper(session, "Known Work")
        target.doi = "10.1234/known"
        target.arxiv_id = "2301.99999"
        target.title_norm = "known work"
        session.add(target)
        session.commit()
        target_id = target.id

        source = _citing_paper_with_refs(
            session,
            "Citing Paper",
            [
                {"raw_ref": "[1] ... Known Work ...", "title": "Known Work", "doi": "10.1234/KNOWN"},  # case differs
                {"raw_ref": "[2] ... Another ...", "title": "Unrelated Work"},
            ],
        )
        source_id = source.id

        updated = match_citations_for_paper(session, source)

    assert updated == 1
    with Session(get_engine()) as session:
        row = session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == source_id)
        ).all()
        matched = next(r for r in row if r.ref_title == "Known Work")
        assert matched.target_paper_id == target_id
        assert matched.match_status == "matched"
        assert matched.match_confidence == 0.95  # doi strategy
        unmatched = next(r for r in row if r.ref_title == "Unrelated Work")
        assert unmatched.match_status == "unmatched"


def test_reverse_backfill_when_cited_paper_ingested_later(client):
    """A cites B; B is added afterwards — B's ingest backfills A's row."""
    with Session(get_engine()) as session:
        source = _citing_paper_with_refs(
            session,
            "Paper A",
            [{"raw_ref": "[5] Later, L. The cited work. 2022.", "title": "The Cited Work", "arxiv_id": "2205.11111"}],
        )

    # B arrives via manual ingest (no full text, reverse-only matching).
    res = client.post(
        "/api/papers/manual",
        json={"title": "The Cited Work", "arxiv_id": "2205.11111", "year": 2022},
    )
    assert res.status_code == 201
    target_id = res.json()["id"]

    with Session(get_engine()) as session:
        row = session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == source.id)
        ).one()
        assert row.target_paper_id == target_id
        assert row.match_status == "matched"
        assert row.match_confidence == 0.9  # arxiv strategy


def test_title_norm_backfill_both_directions(client):
    with Session(get_engine()) as session:
        target = _paper(session, "Semantic Search at Scale")
        target.title_norm = "semantic search at scale"
        session.add(target)
        session.commit()

        source = _citing_paper_with_refs(
            session,
            "Citing Paper",
            [{"raw_ref": "[3] Semantic search at scale!", "title": "Semantic Search at Scale"}],
        )
        updated = match_citations_for_paper(session, source)
    assert updated == 1


def test_match_is_idempotent_and_skips_self_citation(client):
    with Session(get_engine()) as session:
        target = _paper(session, "Known Work")
        target.title_norm = "known work"
        session.add(target)
        session.commit()

        source = _citing_paper_with_refs(
            session,
            "Citing Paper",
            [
                {"raw_ref": "[1] known", "title": "Known Work"},
                {"raw_ref": "[2] self", "title": "Citing Paper"},  # self-citation guard
            ],
        )
        assert match_citations_for_paper(session, source) == 1
        # Re-running: matched rows are not recomputed, self stays unmatched.
        assert match_citations_for_paper(session, source) == 0

        rows = session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == source.id)
        ).all()
        by_title = {r.ref_title: r for r in rows}
        assert by_title["Known Work"].match_status == "matched"
        assert by_title["Citing Paper"].target_paper_id is None


def test_persist_fetched_matches_after_extraction(client):
    """End-to-end: ingest A (cites B by title); B already in library."""
    with Session(get_engine()) as session:
        target = _paper(session, "Attention Is All You Need")
        target.title_norm = "attention is all you need"
        session.add(target)
        session.commit()
        target_id = target.id

    from unittest.mock import patch

    import fitz as _fitz

    doc = _fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Body text about transformers.\n\nReferences\n")
    page.insert_text(
        (72, 110),
        "[1] Vaswani, S. Attention is all you need. In Advances in Neural "
        "Information Processing Systems (2017), pp. 5998-6008.\n",
    )
    buf = BytesIO()
    doc.save(buf)
    doc.close()

    res = client.post(
        "/api/papers/pdf",
        files={"file": ("matcher.pdf", buf.getvalue(), "application/pdf")},
    )
    assert res.status_code == 200
    pid = res.json()["id"]

    with Session(get_engine()) as session:
        row = session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == pid)
        ).first()
        assert row is not None
        assert row.target_paper_id == target_id
        assert row.match_status == "matched"


# ---------------------------------------------------------------------------
# P8.4/P8.5 — graph edge types + per-paper citations API
# ---------------------------------------------------------------------------

def _matched_row(session, source_id, target_id, raw="[1] ref", title=None):
    row = PaperCitation(
        source_paper_id=source_id,
        target_paper_id=target_id,
        raw_ref=raw,
        ref_title=title,
        ref_title_norm=normalize_title(title) or None,
        match_status="matched",
        match_confidence=0.9,
    )
    session.add(row)
    session.commit()
    return row


def test_paper_graph_citation_edges_and_filter(client):
    with Session(get_engine()) as session:
        a = _paper(session, "Paper A")
        b = _paper(session, "Paper B")
        _matched_row(session, a.id, b.id, raw="[1] B ref", title="Paper B")
        a_id, b_id = a.id, b.id

    default = client.get("/api/graph/paper").json()
    # Default (no edge_types) keeps the historical concept-only behavior.
    assert default["edges"] == []

    only_citation = client.get("/api/graph/paper", params={"edge_types": "citation"}).json()
    assert only_citation["edges"] == [
        {"source": a_id, "target": b_id, "weight": 1, "edge_type": "citation"}
    ]

    both = client.get("/api/graph/paper", params={"edge_types": "concept,citation"}).json()
    assert [e for e in both["edges"] if e["edge_type"] == "citation"] == only_citation["edges"]

    assert client.get("/api/graph/paper", params={"edge_types": "bogus"}).status_code == 400
    assert client.get("/api/graph/paper", params={"edge_types": ""}).status_code == 400


def test_paper_citations_endpoint_lists_outgoing_and_incoming(client):
    with Session(get_engine()) as session:
        a = _paper(session, "Paper A")
        b = _paper(session, "Paper B")
        _matched_row(session, a.id, b.id, raw="[2] B cited work", title="Paper B")
        session.add(
            PaperCitation(
                source_paper_id=a.id,
                raw_ref="[3] Unknown, U. An external work. 2021.",
                ref_title="An external work",
                ref_title_norm="an external work",
            )
        )
        session.commit()
        a_id, b_id = a.id, b.id

    res = client.get(f"/api/papers/{a_id}/citations")
    assert res.status_code == 200
    body = res.json()
    assert len(body["outgoing"]) == 2
    matched = next(o for o in body["outgoing"] if o["match_status"] == "matched")
    assert matched["target_paper_id"] == b_id
    assert matched["target_title"] == "Paper B"
    external = next(o for o in body["outgoing"] if o["match_status"] == "unmatched")
    assert external["target_paper_id"] is None
    assert external["raw_ref"].startswith("[3]")

    incoming_res = client.get(f"/api/papers/{b_id}/citations")
    assert incoming_res.status_code == 200
    incoming = incoming_res.json()["incoming"]
    assert len(incoming) == 1
    assert incoming[0]["source_paper_id"] == a_id
    assert incoming[0]["source_title"] == "Paper A"

    assert client.get("/api/papers/99999/citations").status_code == 404
