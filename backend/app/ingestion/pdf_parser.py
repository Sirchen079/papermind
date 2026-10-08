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
    extracted_characters = 0
    try:
        document = fitz.open(stream=pdf_path, filetype="pdf") if isinstance(pdf_path, bytes) else fitz.open(Path(pdf_path))
    except Exception as exc:
        # A failed native open can leave its file stream referenced by locals
        # in PyMuPDF's constructor traceback. Release them before a Windows
        # download context tries to remove the invalid temporary PDF.
        import traceback
        pending, seen = [exc], set()
        while pending:
            failed = pending.pop()
            if id(failed) in seen:
                continue
            seen.add(id(failed))
            traceback.clear_frames(failed.__traceback__)
            pending.extend(cause for cause in (failed.__cause__, failed.__context__) if cause is not None)
        raise
    with document as doc:
        if doc.needs_pass or not doc.is_pdf or doc.page_count == 0:
            raise ValueError("PDF is encrypted or has no pages")
        page_count = doc.page_count
        for number, page in enumerate(doc, 1):
            page_text = page.get_text("text").strip()
            extracted_characters += len(page_text)
            if page_text:
                # Use the same provenance markers as PDF -> Markdown. Skip
                # blank pages without renumbering later pages, and never treat
                # literal markers printed in a PDF as app-generated metadata.
                page_text = page_text.replace('<!-- page:', '&lt;!-- page:')
                parts.append(f'<!-- page:{number} -->\n{page_text}')
    text = "\n\n".join(parts)

    if page_count == 0:
        return "", 0.0
    # A typical text page yields ~2000 chars; scanned pages yield almost none.
    ratio = extracted_characters / (page_count * 2000)
    return text, max(0.0, min(1.0, ratio))
