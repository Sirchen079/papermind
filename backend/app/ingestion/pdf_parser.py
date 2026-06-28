from pathlib import Path

import fitz  # PyMuPDF


def parse_pdf(pdf_path: Path) -> tuple[str, float]:
    """Extract text from a PDF.

    Returns ``(text, parse_confidence)`` where ``parse_confidence`` is a rough
    heuristic in [0, 1]: the ratio of extracted text to a per-page expectation.
    Text PDFs score ~1.0; scanned/image-only PDFs (which need OCR) score near 0,
    so callers can flag low-quality parses.
    """
    pdf_path = Path(pdf_path)
    parts: list[str] = []
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        for page in doc:
            parts.append(page.get_text("text"))
    text = "\n".join(parts).strip()

    if page_count == 0:
        return "", 0.0
    # A typical text page yields ~2000 chars; scanned pages yield almost none.
    ratio = len(text) / (page_count * 2000)
    return text, max(0.0, min(1.0, ratio))
