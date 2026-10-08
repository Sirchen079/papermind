from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Model, Provider
from app.providers import managed

router = APIRouter()


def action(callback):
    try:return callback()
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except (ValueError,OSError) as exc:raise HTTPException(422,str(exc)) from exc


@router.get('/managed-models')
def status():
    return action(lambda:managed.manager().status())


@router.post('/managed-models/import')
def import_model(file:UploadFile=File(...), kind:Literal['chat','embedding']=Form(...),
                 context_window:int=Form(8192,gt=0)):
    return action(lambda:managed.manager().import_stream(file.file,file.filename or 'GGUF 模型',kind,context_window))


@router.post('/managed-models/{mid}/start')
def start(mid:str):
    return action(lambda:managed.manager().start(mid))


@router.post('/managed-models/{mid}/stop')
def stop(mid:str):
    return action(lambda:managed.manager().stop(mid))


@router.delete('/managed-models/{mid}')
def remove(mid:str):
    return action(lambda:managed.manager().remove(mid))


@router.post('/managed-models/{mid}/use')
def use(mid:str,session:Session=Depends(get_session)):
    runtime=managed.manager()
    row=action(lambda:runtime._get(mid))
    # Finish startup before changing the project's existing choice.
    action(lambda:runtime.ready(mid))
    url=managed.PREFIX+mid
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    provider=session.exec(select(Provider).where(Provider.base_url==url,
        Provider.is_deleted==False,Provider.shared_connection_id==None)).first()
    if provider is None:
        provider=Provider(name='内置本机 · '+row['name'],type='openai_compat',base_url=url)
        session.add(provider);session.flush()
    provider.enabled=True;session.add(provider)
    alias='pm-'+mid
    model=session.exec(select(Model).where(Model.provider_id==provider.id,Model.model_id==alias)).first()
    if model is None:
        model=Model(provider_id=provider.id,model_id=alias);session.add(model);session.flush()
    from app.providers.purposes import configured_id
    if configured_id(session,'rerank')==model.id or (row['kind']=='embedding' and configured_id(session,'rerank_llm')==model.id):
        raise HTTPException(422,'该模型正在用于重排序，请先在文档与检索设置中解除。')
    for previous in session.exec(select(Model).where(Model.role_default==row['kind'])).all():
        previous.role_default=None;session.add(previous)
    model.role_default=row['kind'];model.display_name=row['name'];model.context_window=row['context_window']
    session.add(model);session.commit()
    return {'model_id':model.id,'provider_id':provider.id,'kind':row['kind']}
