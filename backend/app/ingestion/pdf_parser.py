from pathlib import Path

import pymupdf as fitz  # PyMuPDF


def parse_pdf(pdf_path: Path | bytes) -> tuple[str, float]:
    """Extract text from a PDF.

    Returns ``(text, parse_confidence)`` where ``parse_confidence`` is a rough
    heuristic in [0, 1]: the ratio of extracted text to a per-page expectation.
    Text PDFs score ~1.0; scanned/image-only PDFs (which need OCR) score near 0,
    so callers can flag low-quality parses.
    """
    parts: list[str] = []
    document = fitz.open(stream=pdf_path, filetype="pdf") if isinstance(pdf_path, bytes) else fitz.open(Path(pdf_path))
    with document as doc:
        if doc.needs_pass or not doc.is_pdf or doc.page_count == 0:
            raise ValueError("PDF is encrypted or has no pages")
        page_count = doc.page_count
        for page in doc:
            parts.append(page.get_text("text"))
    text = "\n".join(parts).strip()

    if page_count == 0:
        return "", 0.0
    # A typical text page yields ~2000 chars; scanned pages yield almost none.
    ratio = len(text) / (page_count * 2000)
    return text, max(0.0, min(1.0, ratio))
