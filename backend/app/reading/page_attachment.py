"""Read one original PDF page into the existing immutable image attachment."""
import base64
import hashlib
from pathlib import Path

import pymupdf

from app.agent.attachments import Attachment, PaperPageReference, prepare_attachment
from app.ingestion.pdf_storage import resolve_pdf


def _digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def page_attachment(paper, page: int, pdf_root: Path) -> Attachment:
    path = resolve_pdf(paper.pdf_path, pdf_root)
    if path is None:
        raise LookupError('这篇论文没有可打开的本地 PDF')
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError('请选择正整数 PDF 页码')
    try:
        before = _digest(path)
        with pymupdf.open(path) as doc:
            if not doc.is_pdf or doc.needs_pass:
                raise ValueError('PDF 无法读取或已加密，请先在阅读器中确认文件')
            if page > doc.page_count:
                raise ValueError(f'这份 PDF 只有 {doc.page_count} 页')
            original = doc[page - 1]
            scale = min(2.5, 2400 / max(original.rect.width, original.rect.height))
            png = original.get_pixmap(matrix=pymupdf.Matrix(scale, scale),
                                     colorspace=pymupdf.csRGB, alpha=False).tobytes('png')
        if _digest(path) != before:
            raise ValueError('PDF 在读取时发生变化，请重新带入该页')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('无法读取这页原图，请重新打开 PDF 后再试') from exc
    result = prepare_attachment(f'P{paper.id}-PDF{page}.png', png)
    raw = base64.b64decode(result.data_url.split(',', 1)[1], validate=True)
    # Keep the page visible even when a long title is clipped in the composer.
    return Attachment(**{**result.model_dump(),
        'name': f'PDF第{page}页 · [P{paper.id}] {paper.title or "论文"}'[:255],
        'paper_page': PaperPageReference(paper_id=paper.id, page=page,
            pdf_sha256=before, image_sha256=hashlib.sha256(raw).hexdigest())})
