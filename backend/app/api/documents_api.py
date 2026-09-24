import tempfile
import re
import zipfile
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from sqlmodel import Session, select
from app.api.deps import get_session
from app.models import Model, Provider, PaperDocument
from app.providers.purposes import purpose_model
from app.reading import documents

router = APIRouter()


@router.get('/document-models')
def model_choices(session: Session = Depends(get_session)):
    choices = {'ocr': [], 'rerank': [], 'rerank_llm': []}
    for model in session.exec(select(Model)).all():
        provider = session.get(Provider, model.provider_id)
        for purpose in choices:
            try:
                purpose_model(session, purpose, model.id)
            except HTTPException:
                continue
            choices[purpose].append({'id': model.id, 'name': model.display_name or model.model_id,
                                    'provider': provider.name, 'supports_images': model.supports_images})
    return choices


class ConvertIn(BaseModel):
    mode: Literal['auto', 'ocr'] = 'auto'
    force: bool = False


@router.get('/papers/{pid}/document')
def document_status(pid: int, session: Session = Depends(get_session)):
    return documents.status(session, pid)


@router.post('/papers/{pid}/document')
def convert(pid: int, body: ConvertIn, session: Session = Depends(get_session)):
    return documents.start(session, pid, body.mode, body.force)


@router.post('/papers/{pid}/document/cancel')
def cancel(pid: int, session: Session = Depends(get_session)):
    return documents.cancel(session, pid)


def published(session, pid):
    documents.status(session, pid)
    row = session.get(PaperDocument, pid)
    if not row or not row.markdown:
        raise HTTPException(404, '尚未生成 Markdown。')
    return row


@router.get('/papers/{pid}/document/markdown')
def markdown(pid: int, session: Session = Depends(get_session)):
    return {'markdown': published(session, pid).markdown}


@router.get('/papers/{pid}/document/download')
def download(pid: int, bundle: bool = False, session: Session = Depends(get_session)):
    row = published(session, pid)
    if not bundle:
        return Response(row.markdown, media_type='text/markdown', headers={'Content-Disposition': f'attachment; filename="paper-{pid}.md"'})
    _, _, root = documents.paper_path(session, pid)
    target = documents.artifact_dir(root, pid, row.published_hash)
    pages = [target / f'page-{page}.png' for page in re.findall(r'<!-- page:(\d+) -->', row.markdown)]
    if any(not path.is_file() for path in pages):
        raise HTTPException(409, '部分原图缺失，请重新转换后导出图文包。Markdown 仍可单独下载。')
    buf = tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024)
    try:
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('document.md', row.markdown)
            for path in pages:
                z.write(path, path.name)
        buf.seek(0)
    except Exception:
        buf.close()
        raise
    return StreamingResponse(iter(lambda: buf.read(65536), b''), media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="paper-{pid}-markdown.zip"'}, background=BackgroundTask(buf.close))


@router.get('/papers/{pid}/document/pages/{page}')
def page_image(pid: int, page: int, session: Session = Depends(get_session)):
    row = published(session, pid)
    _, _, root = documents.paper_path(session, pid)
    path = documents.artifact_dir(root, pid, row.published_hash) / f'page-{page}.png'
    if not path.is_file():
        raise HTTPException(404, 'page not found')
    return FileResponse(path, media_type='image/png')
