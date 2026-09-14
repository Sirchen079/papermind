from typing import Literal
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from app.api.deps import get_session
from app.models import ResearchTask
from app.research import service

router=APIRouter(prefix='/research/tasks',tags=['research'])


class CreateBody(BaseModel):
    request_id: UUID
    question: str = Field(min_length=1,max_length=2000)
    paper_ids: list[int] = Field(min_length=1,max_length=5)
    project_id: int | None = None
    depth: Literal['quick','evidence'] = 'evidence'


class SaveBody(BaseModel):
    expected_version: int = Field(ge=0)
    content: str = Field(min_length=1,max_length=12000)
    evidence_refs: list[str] = Field(default_factory=list,max_length=100)


class VersionBody(BaseModel):
    expected_version: int = Field(ge=1)


class ReviewBody(VersionBody):
    status: Literal['pending','supported','partial','unsupported','unclear']
    note: str = Field(default='',max_length=3000)


class ReuseBody(VersionBody):
    kind: Literal['meeting','plan']


def invoke(fn,*args,**kwargs):
    try:
        return fn(*args,**kwargs)
    except (service.ConflictError,IntegrityError) as exc:
        raise HTTPException(409,'版本冲突，请刷新后核对。'+(str(exc) if isinstance(exc,service.ConflictError) else '')) from exc
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get('')
def list_tasks(session:Session=Depends(get_session), limit:int=Query(50,ge=1,le=100), offset:int=Query(0,ge=0), q:str=Query('',max_length=2000)):
    statement=select(ResearchTask)
    if q.strip():
        statement=statement.where(ResearchTask.question.contains(q.strip(), autoescape=True))
    statement=statement.order_by(ResearchTask.updated_at.desc(), ResearchTask.id.desc()).offset(offset).limit(limit)
    return [t.model_dump(exclude={'run_token','materials_json','steps_json'}) for t in session.exec(statement).all()]


@router.post('',status_code=201)
def create(body:CreateBody,session:Session=Depends(get_session)):
    return invoke(service.create_task,session,str(body.request_id),body.question,body.paper_ids,body.depth,body.project_id)


@router.get('/{task_id}')
def get(task_id:str,session:Session=Depends(get_session)):
    return invoke(service.detail,session,task_id)


@router.post('/{task_id}/run',status_code=202)
def run(task_id:str,background:BackgroundTasks,session:Session=Depends(get_session)):
    token=invoke(service.start_task,session,task_id)
    background.add_task(service.run_task,session.get_bind(),task_id,token)
    return invoke(service.detail,session,task_id)


@router.post('/{task_id}/stop')
def stop(task_id:str,session:Session=Depends(get_session)):
    return invoke(service.stop_task,session,task_id)


@router.post('/{task_id}/artifacts')
def save(task_id:str,body:SaveBody,session:Session=Depends(get_session)):
    return invoke(service.save_artifact,session,task_id,body.content,body.expected_version,body.evidence_refs)


@router.post('/{task_id}/review')
def review(task_id:str,body:ReviewBody,session:Session=Depends(get_session)):
    return invoke(service.review_artifact,session,task_id,body.expected_version,body.status,body.note)


@router.post('/{task_id}/adopt')
def adopt(task_id:str,body:VersionBody,session:Session=Depends(get_session)):
    return invoke(service.adopt_artifact,session,task_id,body.expected_version)


@router.post('/{task_id}/reuse')
def reuse(task_id:str,body:ReuseBody,session:Session=Depends(get_session)):
    return invoke(service.reuse_artifact,session,task_id,body.expected_version,body.kind)
