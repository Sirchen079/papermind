from typing import Literal
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session
from app.api.deps import get_session
from app.models import WikiUpdate
from app.wiki import service

router = APIRouter(prefix='/wiki', tags=['wiki'])


def invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (service.Conflict, IntegrityError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, service.Conflict) else '版本冲突，请刷新后核对') from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class Create(BaseModel):
    request_id: UUID
    title: str = Field(min_length=1, max_length=300)


class PageRef(BaseModel):
    page_id: str = Field(max_length=36)
    number: int = Field(ge=1)


class Save(BaseModel):
    request_id: UUID
    expected_version: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=16000)
    references: list[str] = Field(default_factory=list, max_length=1000)
    paper_ids: list[int] = Field(default_factory=list, max_length=20)
    artifact_ids: list[int] = Field(default_factory=list, max_length=20)
    page_refs: list[PageRef] = Field(default_factory=list, max_length=5)
    cite_added: bool = False
    support_status: Literal['pending','supported','partial','unsupported','unclear'] = 'pending'
    review_note: str = Field(default='', max_length=3000)
    change_note: str = Field(default='', max_length=3000)


class Adopt(BaseModel):
    expected_version: int = Field(ge=0)
    number: int = Field(ge=1)


class Patch(BaseModel):
    expected_version: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    archived: bool | None = None


class Update(BaseModel):
    request_id: UUID
    expected_version: int = Field(ge=0)
    paper_ids: list[int] = Field(default_factory=list, max_length=20)
    artifact_ids: list[int] = Field(default_factory=list, max_length=20)


class Retain(BaseModel):
    request_id: UUID
    expected_version: int = Field(ge=0)


class Copy(BaseModel):
    request_id: UUID
    target_workspace: str = Field(pattern=r'^(legacy|[a-f0-9]{32})$')
    number: int = Field(ge=1)


@router.get('/pages')
def list_pages(q: str = Query('',max_length=2000), archived:bool=False, session:Session=Depends(get_session)):
    return service.list_pages(session,q,archived)


@router.post('/pages',status_code=201)
def create(body:Create,session:Session=Depends(get_session)):
    return invoke(service.create,session,str(body.request_id),body.title)


@router.get('/pages/{page_id}')
def detail(page_id:str,session:Session=Depends(get_session)):
    return invoke(service.detail,session,page_id)


@router.post('/pages/{page_id}/revisions')
def save(page_id:str,body:Save,session:Session=Depends(get_session)):
    return invoke(service.save,session,page_id,body.model_dump(mode='json'))


@router.get('/pages/{page_id}/revisions/{number}')
def read_revision(page_id:str,number:int,session:Session=Depends(get_session)):
    return invoke(service.revision_detail,session,page_id,number)


@router.post('/pages/{page_id}/adopt')
def adopt(page_id:str,body:Adopt,session:Session=Depends(get_session)):
    return invoke(service.adopt,session,page_id,body.expected_version,body.number)


@router.patch('/pages/{page_id}')
def patch(page_id:str,body:Patch,session:Session=Depends(get_session)):
    return invoke(service.patch,session,page_id,body.expected_version,body.title,body.archived)


@router.post('/pages/{page_id}/updates',status_code=202)
def update(page_id:str,body:Update,background:BackgroundTasks,session:Session=Depends(get_session)):
    result, launch = invoke(service.start_update,session,page_id,str(body.request_id),body.expected_version,body.paper_ids,body.artifact_ids)
    if launch:
        background.add_task(service.run_update,session.get_bind(),result['id'])
    return result


@router.get('/updates/{update_id}')
def get_update(update_id:str,session:Session=Depends(get_session)):
    row=session.get(WikiUpdate,update_id)
    if row is None:
        raise HTTPException(404,'专题更新任务不存在')
    return service.public_update(row)


@router.post('/updates/{update_id}/save-candidate')
def retain(update_id:str,body:Retain,session:Session=Depends(get_session)):
    return invoke(service.save_conflict,session,update_id,str(body.request_id),body.expected_version)


@router.post('/pages/{page_id}/copy-to-workspace',status_code=201)
def copy(page_id:str,body:Copy,request:Request):
    from app.wiki.copying import copy_topic
    from app.workspaces.context import current_workspace
    return invoke(copy_topic,request.app.state.workspaces,current_workspace.get(),body.target_workspace,page_id,body.number,str(body.request_id))


@router.post('/updates/{update_id}/retry',status_code=202)
def retry(update_id:str,background:BackgroundTasks,session:Session=Depends(get_session)):
    result,launch=invoke(service.retry_update,session,update_id)
    if launch:
        background.add_task(service.run_update,session.get_bind(),update_id)
    return result


@router.get('/pages/{page_id}/export')
def export(page_id:str,number:int=Query(ge=1),session:Session=Depends(get_session)):
    content=invoke(service.export_markdown,session,page_id,number)
    return Response(content,media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="papermind-topic.md"'})


@router.get('/search')
def search(q:str=Query(min_length=1,max_length=2000),session:Session=Depends(get_session)):
    return service.search_adopted(session,q)
