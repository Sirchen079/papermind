"""Copy paper snapshots. No source-engine references survive in the target."""
import hashlib
import re
import shutil
from sqlalchemy import text
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.ingestion.dedup import normalize_title
from app.ingestion.pdf_storage import resolve_pdf
from app.models import Paper, PaperNote, PaperExcerpt, PaperDocument, WorkspaceCopy
from app.workspaces.context import bind_workspace


class CopyConflict(ValueError):
    pass


def copy_paper(registry, origin, target_id, paper_id, request_id, include_notes=False):
    if origin.id == target_id:
        raise CopyConflict('请选择另一个研究项目。')
    target = registry.get(target_id)
    if target['archived']:
        raise CopyConflict('目标项目已归档，请先恢复该项目。')
    reason = registry.unavailable_reason(target_id)
    if reason:
        raise CopyConflict(reason)
    destination = registry.context(target_id)
    with bind_workspace(destination):
        engine = get_engine()
    pdf_file = None
    document_files = []
    committed = False
    try:
        with Session(engine) as dest:
            # Serialize the duplicate check, receipt and file publication.
            dest.exec(text('BEGIN IMMEDIATE'))
            receipt = dest.get(WorkspaceCopy, request_id)
            if receipt:
                if (receipt.source_workspace, receipt.source_paper_id, receipt.include_notes) != (origin.id, paper_id, include_notes):
                    raise CopyConflict('这次复制的参数发生变化，请重新发起复制。')
                copied = dest.get(Paper, receipt.paper_id)
                if copied is None or copied.is_deleted:
                    raise CopyConflict('原目标副本已移除；需要再次复制时，请重新发起。')
                return {**receipt.model_dump(mode='json'), 'reused': True}

            with bind_workspace(origin), Session(get_engine()) as source:
                source.exec(text('BEGIN'))
                paper = source.get(Paper, paper_id)
                if paper is None or paper.is_deleted:
                    raise LookupError('原项目中找不到这篇论文。')
                title_norm = normalize_title(paper.title or '')
                for existing in dest.exec(select(Paper).where(Paper.is_deleted == False)):
                    same_doi = paper.doi and existing.doi and paper.doi.strip().lower() == existing.doi.strip().lower()
                    same_arxiv = paper.arxiv_id and existing.arxiv_id and paper.arxiv_id.strip() == existing.arxiv_id.strip()
                    same_title = title_norm and title_norm == normalize_title(existing.title or '')
                    if same_doi or same_arxiv or same_title:
                        raise CopyConflict(f'目标项目已有同一篇论文（#{existing.id}），请在目标项目中查看。')

                fields = paper.model_dump(exclude={'id', 'created_at', 'updated_at', 'is_deleted', 'pdf_path'})
                # A local import path is not a live link into the source project.
                if paper.source == 'pdf':
                    fields['source_ref'] = None
                if fields['citation_key'] and dest.exec(select(Paper.id).where(Paper.citation_key == fields['citation_key'], Paper.is_deleted == False)).first():
                    fields['citation_key'] = None
                copied = Paper(**fields)
                pdf_sha = None
                if paper.pdf_path:
                    original_pdf = resolve_pdf(paper.pdf_path, origin.data_dir / 'pdfs')
                    if original_pdf is None:
                        raise CopyConflict('原项目的 PDF 无法读取，请恢复原文后再复制。')
                    root = destination.data_dir / 'pdfs'
                    root.mkdir(parents=True, exist_ok=True)
                    # Keep names compact for Windows data roots nested inside
                    # workspace directories; the receipt carries provenance.
                    pdf_file = root / f'c{request_id}.pdf'
                    digest = hashlib.sha256()
                    with original_pdf.open('rb') as reader, pdf_file.open('wb') as writer:
                        for chunk in iter(lambda: reader.read(1024 * 1024), b''):
                            writer.write(chunk)
                            digest.update(chunk)
                    copied.pdf_path = pdf_file.name
                    pdf_sha = digest.hexdigest()
                dest.add(copied)
                dest.flush()
                document = source.get(PaperDocument, paper_id)
                if document and document.markdown and document.published_hash == pdf_sha:
                    from app.reading.documents import artifact_dir
                    source_dir = artifact_dir(origin.data_dir / 'pdfs', paper_id, pdf_sha)
                    target_dir = artifact_dir(destination.data_dir / 'pdfs', copied.id, pdf_sha)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    for page in re.findall(r'<!-- page:(\d+) -->', document.markdown):
                        original = source_dir / f'page-{page}.png'
                        if original.is_file():
                            target_file = target_dir / original.name
                            document_files.append(target_file)
                            shutil.copyfile(original, target_file)
                    markdown_file = target_dir / 'document.md'
                    document_files.append(markdown_file)
                    markdown_file.write_text(document.markdown, encoding='utf-8')
                    # Project-specific model IDs and in-flight jobs never cross projects.
                    dest.add(PaperDocument(paper_id=copied.id, source_hash=pdf_sha, published_hash=pdf_sha,
                        status='ready', markdown=document.markdown, model_name=document.model_name,
                        total_pages=len(re.findall(r'<!-- page:(\d+) -->', document.markdown)),
                        pages_json=document.pages_json if document.source_hash == pdf_sha else '[]',
                        index_status='unconfigured'))
                if include_notes:
                    for model in (PaperNote, PaperExcerpt):
                        for row in source.exec(select(model).where(model.paper_id == paper_id)):
                            values = row.model_dump(exclude={'id', 'paper_id'})
                            dest.add(model(paper_id=copied.id, **values))
                receipt = WorkspaceCopy(request_id=request_id, source_workspace=origin.id,
                    source_name=origin.name, source_paper_id=paper_id, source_updated_at=paper.updated_at,
                    paper_id=copied.id, include_notes=include_notes, pdf_sha256=pdf_sha)
                dest.add(receipt)
                dest.commit()
                committed = True
                dest.refresh(receipt)
                return {**receipt.model_dump(mode='json'), 'reused': False}
    finally:
        if not committed:
            for path in document_files:
                path.unlink(missing_ok=True)
        if pdf_file is not None and not committed:
            pdf_file.unlink(missing_ok=True)
