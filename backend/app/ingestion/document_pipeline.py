"""PDF import schedules the existing resumable Markdown transcription worker."""
import json
from sqlmodel import Session, select
from fastapi import HTTPException
from app.models import Paper, PaperDocument, Setting


def import_mode(session):
    row = session.get(Setting, 'pdf_ingest_mode')
    return row.value if row and row.value in {'ocr', 'auto', 'advanced', 'manual'} else 'ocr'


def waiting_for_markdown(session, paper):
    row = session.get(PaperDocument, paper.id)
    return bool(row and json.loads(row.followup_json).get('ingest') and not row.markdown)


def queue_import(session, paper, provider=None, model_id=None):
    from app.reading import documents
    mode = import_mode(session)
    if mode == 'manual':
        return False
    row = session.get(PaperDocument, paper.id) or PaperDocument(paper_id=paper.id)
    row.mode = mode
    import pymupdf
    _, path, _ = documents.paper_path(session, paper.id)
    with pymupdf.open(path) as pdf:
        row.total_pages = pdf.page_count
    followup = {'ingest': True}
    if provider is not None and model_id:
        followup['analysis'] = {'provider_id': provider.id, 'model_id': model_id}
    row.followup_json = json.dumps(followup)
    # Persist before dispatch, so a crash between save and submit can be resumed.
    row.status = 'queued'
    session.add(row)
    session.commit()
    _start_or_wait(session, paper.id, mode)
    return True


def _start_or_wait(session, pid, mode):
    from app.reading import documents
    try:
        documents.start(session, pid, mode)
    except HTTPException as exc:
        if exc.status_code == 409:
            return
        row = session.get(PaperDocument, pid)
        row.status = 'waiting_model' if exc.status_code == 422 else 'error'
        row.error = str(exc.detail)
        session.add(row)
        session.commit()
    except Exception as exc:
        documents._log_failure(exc, pid, 0, 'load')
        row = session.get(PaperDocument, pid)
        row.status, row.error = 'error', 'PDF 已保存，但未能启动转换。请在 OCR 与 Markdown 面板重试。'
        session.add(row)
        session.commit()


def resume_imports(engine, *, waiting_only=False):
    """Only imports created by this pipeline resume; legacy papers stay intact."""
    statuses = {'waiting_model'} if waiting_only else {'waiting_model', 'queued', 'running', 'interrupted'}
    with Session(engine) as session:
        rows = session.exec(select(PaperDocument).where(PaperDocument.status.in_(statuses))).all()
        pending = [(r.paper_id, r.mode) for r in rows if json.loads(r.followup_json).get('ingest')]
        session.commit()
        for pid, mode in pending:
            paper = session.get(Paper, pid)
            if paper and not paper.is_deleted:
                _start_or_wait(session, pid, mode)


def finish_import(session, pid):
    """Run the originally requested analysis and citation extraction on Markdown."""
    row = session.get(PaperDocument, pid)
    followup = json.loads(row.followup_json)
    if not followup.get('ingest') or followup.get('finished'):
        return
    analysis = followup.get('analysis')
    ctx = None
    if analysis and not followup.get('analysis_started'):
        from app.models import Provider, Model
        from app.providers.purposes import configured_id
        from app.providers.shared import resolve
        from app.providers.client import ProviderClient
        provider = session.get(Provider, analysis['provider_id'])
        ocr = session.get(Model, configured_id(session, 'ocr')) if configured_id(session, 'ocr') else None
        only_ocr = bool(ocr and ocr.provider_id == analysis['provider_id'] and ocr.model_id == analysis['model_id'] and ocr.role_default != 'chat')
        if provider and provider.enabled and not provider.is_deleted and not only_ocr:
            try:
                actual, crypto = resolve(provider)
                if actual.enabled:
                    engine = session.get_bind()
                    ctx = (ProviderClient(lambda: Session(engine), crypto), actual, analysis['model_id'])
            except LookupError:
                pass
        # Never silently repeat costly analysis after a process interruption.
        followup['analysis_started'] = True
        row.followup_json = json.dumps(followup)
        session.add(row)
        session.commit()
    from app.ingestion.service import _finish_import
    paper = session.get(Paper, pid)
    _finish_import(session, paper, *(ctx or (None, None, None)), index=False)
    row = session.get(PaperDocument, pid)
    followup['finished'] = True
    row.followup_json = json.dumps(followup)
    session.add(row)
    session.commit()
