"""Prepare cached text independently of the PDF display and request session."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from threading import Lock

from fastapi import HTTPException
from sqlmodel import Session

from app.config import get_settings
from app.models import Paper
from app.ingestion.pdf_parser import parse_pdf
from app.ingestion.pdf_storage import resolve_pdf

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reading-parse")
_lock = Lock()
_jobs = {}


def _parse(engine, pid, stored_path, path, fingerprint):
    text, confidence = parse_pdf(path)
    if not text.strip():
        raise ValueError("这份 PDF 没有可提取的文字，可能是扫描件。请先 OCR；仍可阅读和讨论选中文字。")
    with Session(engine) as session:
        paper = session.get(Paper, pid)
        if not paper or paper.is_deleted or paper.pdf_path != stored_path or _fingerprint(path) != fingerprint:
            raise ValueError("论文文件已变更，请重新加载。")
        if not paper.full_text or not paper.full_text.strip():
            paper.full_text = text
            paper.parse_confidence = confidence
            session.add(paper)
            session.commit()


def _fingerprint(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def prepare(session, pid, retry=False):
    paper = session.get(Paper, pid)
    if not paper or paper.is_deleted:
        raise HTTPException(404, "paper not found")
    if paper.full_text and paper.full_text.strip():
        with _lock:
            _jobs.pop((session.get_bind(), pid), None)
        return {"status": "ready", "message": "论文已加载，伴读可使用全文"}
    path = resolve_pdf(paper.pdf_path, Path(get_settings().data_dir).resolve() / "pdfs") if paper.pdf_path else None
    if path is None:
        return {"status": "error", "message": "找不到论文 PDF，请重新上传文件。"}
    engine = session.get_bind()
    key = (engine, pid)
    fingerprint = _fingerprint(path)
    with _lock:
        previous = _jobs.get(key)
        if previous and previous[0] == (paper.pdf_path, fingerprint):
            future = previous[1]
            if not future.done():
                return {"status": "loading", "message": "论文加载中…正在后台解析全文"}
            error = future.exception()
            if error and not retry:
                return {"status": "error", "message": str(error)}
            if not error:
                return {"status": "ready", "message": "论文已加载，伴读可使用全文"}
        future = _pool.submit(copy_context().run, _parse, engine, pid, paper.pdf_path, path, fingerprint)
        _jobs[key] = ((paper.pdf_path, fingerprint), future)
    return {"status": "loading", "message": "论文加载中…正在后台解析全文"}
