from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Setting

router = APIRouter()


class SettingIn(BaseModel):
    value: str | None = None


@router.get("/settings")
def list_settings(session: Session = Depends(get_session)) -> dict:
    return {r.key: r.value for r in session.exec(select(Setting)).all()}


@router.get("/settings/{key}")
def get_setting(key: str, session: Session = Depends(get_session)) -> dict:
    row = session.get(Setting, key)
    if row is None:
        raise HTTPException(404, "setting not found")
    return {"key": row.key, "value": row.value}


@router.put("/settings/{key}")
def upsert_setting(key: str, body: SettingIn, session: Session = Depends(get_session)) -> dict:
    if key == 'rerank_mode' and body.value not in {'off', 'dedicated', 'llm'}:
        raise HTTPException(422, '请选择关闭、专用模型或大模型重排序模式。')
    if key in {'ocr_model_config_id', 'rerank_model_config_id', 'rerank_llm_model_config_id'} and body.value:
        from app.providers.purposes import purpose_model
        try:
            model_id = int(body.value)
        except ValueError as exc:
            raise HTTPException(422, '请选择有效模型。') from exc
        purpose_model(session, key.removesuffix('_model_config_id'), model_id)
        body.value = str(model_id)
    if key == "translation_model_config_id" and body.value:
        from app.api.chat_api import pick_chat_model
        try:
            model_id = int(body.value)
        except ValueError as exc:
            raise HTTPException(422, "请选择有效的翻译模型。") from exc
        if model_id <= 0:
            raise HTTPException(422, "请选择有效的翻译模型。")
        pick_chat_model(session, model_id)
        body.value = str(model_id)
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=body.value)
    else:
        row.value = body.value
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"key": row.key, "value": row.value}


@router.delete("/settings/{key}", status_code=204)
def delete_setting(key: str, session: Session = Depends(get_session)) -> None:
    row = session.get(Setting, key)
    if row is not None:
        session.delete(row)
        session.commit()
