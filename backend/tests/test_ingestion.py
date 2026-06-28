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
