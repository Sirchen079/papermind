from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from sqlmodel import Session
from app.api.deps import get_session
from app.ingestion import institutional as access, institutional_jobs as jobs
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
