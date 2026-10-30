from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from typing import Literal
from sqlmodel import Session
from app.api.deps import get_session
from app.ingestion import institutional as access, institutional_jobs as jobs, institutional_setup as setup
from app.security.local_token import require_local_token

router = APIRouter(prefix='/institutional', dependencies=[Depends(require_local_token)])


class Preferences(BaseModel):
    model_config = {'extra': 'forbid'}
    institution: str = Field(min_length=1, max_length=200)
    aliases: str = Field(default='', max_length=500)
    library_url: str = Field(default='', max_length=2000)


class Download(BaseModel):
    model_config = {'extra': 'forbid'}
    paper_ids: list[int] = Field(min_length=1, max_length=10)
    mode: Literal['auto', 'manual'] = 'auto'


@router.get('/environment')
def environment_status():
    return setup.status()


@router.post('/environment', status_code=202)
def install_environment():
    return setup.start()


@router.get('/config')
def config():
    return {**access.config(), 'ready': access.runtime.ready()}


@router.put('/config')
def configure(body: Preferences):
    try:
        return access.configure(body.institution, body.library_url, body.aliases)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/jobs')
def start(body: Download, session: Session = Depends(get_session)):
    if body.mode == 'manual' and len(body.paper_ids) != 1:
        raise HTTPException(422, '浏览器手动下载请每次选择一篇论文。')
    return jobs.start(session, body.paper_ids, body.mode)


router.add_api_route('/jobs', jobs.list_jobs, methods=['GET'])
router.add_api_route('/jobs/{job_id}', jobs.get_job, methods=['GET'])
router.add_api_route('/jobs/{job_id}/stop', jobs.cancel, methods=['POST'])


@router.post('/jobs/{job_id}/papers/{paper_id}/pdf')
async def upload_pdf(job_id: str, paper_id: int, file: UploadFile = File(...), session: Session = Depends(get_session)):
    from starlette.concurrency import run_in_threadpool
    data = await file.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024 or not data.startswith(b'%PDF-'):
        raise HTTPException(422, '请选择不超过 100 MB 的正文 PDF。')
    return await run_in_threadpool(jobs.attach_uploaded, session, job_id, paper_id, data)
