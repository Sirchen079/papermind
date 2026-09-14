from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session
from app.api.deps import get_session
from app.models import Provider
from app.providers import shared
from app.security.url_guard import ensure_http_url

router=APIRouter()


class AttachIn(BaseModel):
    connection_id:str=Field(pattern=r'^[a-f0-9]{32}$')


class SharedPatch(BaseModel):
    expected_version:int=Field(ge=1)
    name:str|None=Field(default=None,min_length=1,max_length=120)
    base_url:str|None=Field(default=None,max_length=2000)
    api_key:str|None=Field(default=None,max_length=20000)
    enabled:bool|None=None

    @field_validator('name')
    @classmethod
    def trim_name(cls,value):
        if value is not None and not value.strip():raise ValueError('请输入连接名称')
        return value.strip() if value else value

    @field_validator('base_url')
    @classmethod
    def valid_url(cls,value):
        return ensure_http_url(value) if value else value


def invoke(fn,*args):
    from app.security.crypto import MissingKeyError
    try:return fn(*args)
    except MissingKeyError as exc:raise HTTPException(409,str(exc)) from exc
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except shared.SharedConflict as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


def require_provider(session,pid):
    provider=session.get(Provider,pid)
    if provider is None or provider.is_deleted:raise HTTPException(404,'provider not found')
    return provider


@router.get('/shared-connections')
def list_connections():
    return shared.list_connections()


@router.patch('/shared-connections/{connection_id}')
def update_connection(connection_id:str,body:SharedPatch):
    return invoke(shared.update,connection_id,body.expected_version,body.model_dump(exclude_none=True,exclude={'expected_version'}))


@router.post('/providers/{pid}/share')
def publish(pid:int,session:Session=Depends(get_session)):
    return invoke(shared.publish,session,require_provider(session,pid))


@router.post('/providers/attach',status_code=201)
def attach(body:AttachIn,session:Session=Depends(get_session)):
    from app.api.providers_api import _public
    return _public(invoke(shared.attach,session,body.connection_id))


@router.post('/providers/{pid}/detach')
def detach(pid:int,session:Session=Depends(get_session)):
    from app.api.providers_api import _public
    return _public(invoke(shared.detach,session,require_provider(session,pid)))
