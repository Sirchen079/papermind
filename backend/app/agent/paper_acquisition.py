"""Connect a discovered full text to the existing local paper reading workflow."""
import json
import logging
from pathlib import Path
from urllib.parse import quote, urlsplit

import pymupdf
from app.config import get_settings
from app.ingestion.pdf_download import download_pdf, check_cancelled
from app.ingestion.pdf_storage import resolve_pdf
from app.ingestion.service import persist_fetched, find_duplicate
from app.ingestion.sources import FetchedPaper
from app.models import Paper


def _result(paper, path, receipt, status, indexing=None, metadata=None, document=None):
    from app.workspaces.context import current_workspace
    workspace = current_workspace.get()
    base = f'/api/w/{quote(workspace.id, safe="")}' if workspace else '/api'
    with pymupdf.open(path) as doc:
        pages = doc.page_count
        preview = doc[0].get_text().strip()[:500]
    return json.dumps({'ok': True, 'paper_id': paper.id, 'title': paper.title,
        'status': status, 'pages': pages, 'full_text_chars': len(paper.full_text or ''),
        'file_url': f'{base}/papers/{paper.id}/file', 'download': receipt,
        'indexing': indexing, 'document': document, 'metadata': metadata or (receipt or {}).get('metadata'), 'first_page_preview': preview,
        'next': 'PDF 已保存，全文 OCR → Markdown → 索引尚未完成；请在论文详情查看进度。等待配置时需选择 OCR 模型，识别失败时可继续未完成的页面。当前预览仅来自 PDF 第一页，不能据此声称已读全文。'
                if document and not document['has_markdown'] else 'PDF 已在当前论文库。先核对题名，再用 get_paper_full_text 按章节或 PDF 页阅读；search_paper_text 可检索正文。下载成功不代表已读完整论文。'
                if paper.full_text else 'PDF 已保存，未提取到文本；需要通过现有 PDF 转 Markdown/OCR 流程处理。'}, ensure_ascii=False)


def _arxiv_id(url):
    parsed = urlsplit(url)
    if parsed.hostname not in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'} or not parsed.path.startswith('/pdf/'):
        return None
    from app.ingestion.sources import normalize_arxiv_id
    try:
        return normalize_arxiv_id(parsed.path[len('/pdf/'):])
    except ValueError:
        return None


def _arxiv_metadata(url):
    """Reuse the arXiv importer for an identified direct PDF, without guessing IDs."""
    arxiv_id = _arxiv_id(url)
    if arxiv_id is None:
        return None, None
    from app.ingestion.sources import fetch_arxiv
    try:
        import arxiv
        from functools import partial
        client = arxiv.Client(num_retries=0)
        # arxiv.Client currently exposes no timeout option. Adapt only this
        # lookup's session, leaving ordinary arXiv imports and other clients alone.
        client._session.get = partial(client._session.get, timeout=15)
        try:
            fetched = fetch_arxiv(arxiv_id, client=client, download_pdf=False)
        finally:
            client._session.close()
        return fetched, {'status': 'retrieved', 'source': 'arxiv', 'identifier': arxiv_id}
    except Exception as exc:
        # Bibliographic lookup must not make the available full text unusable.
        return None, {'status': 'unavailable', 'source': 'arxiv', 'identifier': arxiv_id,
                      'error_type': type(exc).__name__}


def _doi_metadata(doi):
    from app.ingestion.sources import lookup_doi_metadata
    return lookup_doi_metadata(doi)


def import_paper_pdf(session, url, paper_id=None, title=None, doi=None, cancelled=None):
    """Attach missing full text; repeat calls reuse the local document."""
    from app.security.url_guard import ensure_http_url
    ensure_http_url(url)
    check_cancelled(cancelled)
    root = Path(get_settings().data_dir)
    paper = session.get(Paper, paper_id) if paper_id is not None else find_duplicate(session, doi, _arxiv_id(url), title)
    if paper_id is not None and (paper is None or paper.is_deleted):
        raise ValueError('指定的论文不存在或已删除。')
    if paper is None and not (title or '').strip():
        raise ValueError('新论文请提供已核对的题名；已有论文请提供 paper_id。')
    if paper is not None:
        existing = resolve_pdf(paper.pdf_path, root / 'pdfs')
        if existing is not None:
            receipt_path = existing.with_suffix('.source.json')
            try:
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                receipt = None
            from app.models import PaperDocument
            from app.reading.documents import snapshot
            row = session.get(PaperDocument, paper.id)
            return _result(paper, existing, receipt, 'already_available', document=snapshot(row) if row else None)
    target_id = paper.id if paper is not None else None
    # This operation adds full text to the known identity; it does not rewrite
    # curated bibliographic metadata from a download filename or model guess.
    fetched = FetchedPaper(source='public_pdf', source_ref=url,
                           title=None if paper else title.strip(), doi=None if paper else doi)
    metadata = None
    if paper is None:
        verified, metadata = _arxiv_metadata(url)
        if metadata is None:
            verified, metadata = _doi_metadata(doi)
        check_cancelled(cancelled)
        if verified is not None:
            fetched.authors = verified.authors
            fetched.abstract = verified.abstract
            fetched.year = verified.year
            for field in ("venue", "volume", "issue", "pages"):
                setattr(fetched, field, getattr(verified, field))
            fetched.arxiv_id = verified.arxiv_id
            fetched.doi = doi or verified.doi
    try:
        with download_pdf(url, root, cancelled) as (path, receipt):
            if metadata is not None:
                receipt['metadata'] = metadata
            fetched.pdf_file = path
            check_cancelled(cancelled)
            paper = persist_fetched(session, fetched, root / 'pdfs', target_paper_id=target_id)
    except Exception:
        session.rollback()
        raise
    stored = resolve_pdf(paper.pdf_path, root / 'pdfs')
    try:
        with stored.with_suffix('.source.json').open('x', encoding='utf-8') as output:
            json.dump(receipt, output, ensure_ascii=False, indent=2)
    except FileExistsError:
        pass
    except OSError:
        logging.getLogger(__name__).warning('PDF acquisition receipt could not be written')
    from app.rag.index import index_local_paper, index_paper
    from app.ingestion.document_pipeline import waiting_for_markdown
    if waiting_for_markdown(session, paper):
        from app.models import PaperDocument
        from app.reading.documents import snapshot
        return _result(paper, stored, receipt, 'imported',
                       {'local_chunks': 0, 'embedded_chunks': 0, 'status': 'waiting_markdown'}, metadata,
                       snapshot(session.get(PaperDocument, paper.id)))
    indexing = {'local_chunks': index_local_paper(session, paper), 'embedded_chunks': 0, 'status': 'local_only'}
    if cancelled is None or not cancelled.is_set():
        try:
            indexing['embedded_chunks'] = index_paper(session, paper)
            if indexing['embedded_chunks']:
                indexing['status'] = 'ready'
        except Exception as exc:
            session.rollback()
            indexing['error_type'] = type(exc).__name__
            logging.getLogger(__name__).warning('Downloaded PDF retained with local search; embedding unavailable (%s)', type(exc).__name__)
    return _result(paper, stored, receipt, 'imported', indexing, metadata)
