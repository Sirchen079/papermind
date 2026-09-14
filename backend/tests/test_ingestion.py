from pathlib import Path

import fitz

from app.ingestion.dedup import normalize_title
from app.ingestion.pdf_parser import parse_pdf


def test_normalize_title():
    assert normalize_title("Attention Is All You Need!") == "attention is all you need"
    assert normalize_title("Café — résumé") == "cafe resume"
    assert normalize_title("") == ""
    assert normalize_title(None) == ""
    # case/accent/punctuation differences collapse to the same key
    assert normalize_title("Self-Attention") == normalize_title("self attention")


def _make_pdf(path: Path, text: str, pages: int = 1) -> None:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def test_parse_pdf_extracts_text(tmp_path):
    p = tmp_path / "p.pdf"
    _make_pdf(p, "A novel method for training neural networks. ")
    text, conf = parse_pdf(p)
    assert "novel method" in text
    assert 0.0 < conf <= 1.0


def test_parse_pdf_blank_pages_low_confidence(tmp_path):
    p = tmp_path / "blank.pdf"
    _make_pdf(p, "", pages=3)  # genuinely empty pages (like a scanned doc pre-OCR)
    text, conf = parse_pdf(p)
    assert text == ""
    assert conf < 0.1


# ---------------------------------------------------------------------------
# Best-effort pipeline steps: swallow the failure, log a WARNING with traceback
# ---------------------------------------------------------------------------

import logging

from sqlmodel import Session

from app.db.engine import get_engine
from app.ingestion.service import persist_fetched
from app.ingestion.sources import FetchedPaper
from app.models import Paper


def test_persist_fetched_citation_match_failure_logs_warning_and_continues(
    client, tmp_path, monkeypatch, caplog
):
    """Citation matching is best-effort: when it raises, ingest still succeeds
    and the service logs a WARNING naming the step and paper id, with the
    exception attached via exc_info (not interpolated into the message)."""

    def _boom(session, paper):
        raise RuntimeError("citation matching exploded")

    # persist_fetched imports this at call time, so patching the source module
    # attribute is picked up inside the ingest flow.
    monkeypatch.setattr(
        "app.ingestion.citation_match.match_citations_for_paper", _boom
    )

    fetched = FetchedPaper(source="manual", title="Best Effort Logging Paper")

    with caplog.at_level(logging.WARNING, logger="app.ingestion.service"):
        with Session(get_engine()) as session:
            paper = persist_fetched(session, fetched, pdf_dir=tmp_path)
            paper_id = paper.id

    # Main flow still succeeded: the paper was persisted and returned.
    assert paper_id is not None
    with Session(get_engine()) as session:
        stored = session.get(Paper, paper_id)
        assert stored is not None
        assert stored.title == "Best Effort Logging Paper"

    # The swallowed failure surfaced as exactly one WARNING from the service.
    records = [
        r
        for r in caplog.records
        if r.name == "app.ingestion.service" and r.levelno == logging.WARNING
    ]
    assert len(records) == 1
    rec = records[0]
    assert "citation_matching" in rec.getMessage()
    assert str(paper_id) in rec.getMessage()
    assert rec.exc_info is not None
    assert rec.exc_info[0] is RuntimeError
