from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Model, Provider
from app.models.base import utcnow
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto

router = APIRouter()


class ProviderIn(BaseModel):
    name: str
    type: str
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True


class ProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None


def _public(p: Provider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "type": p.type,
        "base_url": p.base_url,
        "enabled": p.enabled,
    }


def _client(session: Session) -> ProviderClient:
    return ProviderClient(session_factory=lambda: session, crypto=get_crypto())


@router.get("/providers")
def list_providers(session: Session = Depends(get_session)) -> list[dict]:
    return [_public(p) for p in session.exec(select(Provider)).all()]


@router.post("/providers")
def create_provider(body: ProviderIn, session: Session = Depends(get_session)) -> dict:
    crypto = get_crypto()
    p = Provider(
        name=body.name,
        type=body.type,
        base_url=body.base_url,
        enabled=body.enabled,
        api_key_encrypted=crypto.encrypt(body.api_key) if body.api_key else None,
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return _public(p)


@router.patch("/providers/{pid}")
def patch_provider(pid: int, body: ProviderPatch, session: Session = Depends(get_session)) -> dict:
    p = session.get(Provider, pid)
    if p is None:
        raise HTTPException(404, "provider not found")
    if body.name is not None:
        p.name = body.name
    if body.base_url is not None:
        p.base_url = body.base_url
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.api_key is not None:
        p.api_key_encrypted = get_crypto().encrypt(body.api_key)
    p.updated_at = utcnow()
    session.add(p)
    session.commit()
    session.refresh(p)
    return _public(p)


@router.delete("/providers/{pid}", status_code=204)
def delete_provider(pid: int, session: Session = Depends(get_session)) -> None:
    p = session.get(Provider, pid)
    if p is None:
        return
    # App-level cascade: delete child models first so the FK constraint
    # (enforced with PRAGMA foreign_keys=ON) doesn't block provider deletion.
    for m in session.exec(select(Model).where(Model.provider_id == pid)).all():
        session.delete(m)
    session.delete(p)
    session.commit()


@router.post("/providers/{pid}/models/refresh")
def refresh_models(pid: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Provider, pid)
    if p is None:
        raise HTTPException(404, "provider not found")
    fetched = _client(session).list_models(p)
    for existing in session.exec(select(Model).where(Model.provider_id == pid)).all():
        session.delete(existing)
    now = utcnow()
    for m in fetched:
        session.add(
            Model(
                provider_id=pid,
                model_id=m.model_id,
                display_name=m.display_name,
                context_window=m.context_window,
                fetched_at=now,
                is_manual=False,
            )
        )
    session.commit()
    return {"count": len(fetched)}


@router.get("/providers/{pid}/models")
def list_provider_models(pid: int, session: Session = Depends(get_session)) -> list[dict]:
    return [
        {
            "id": m.id,
            "model_id": m.model_id,
            "display_name": m.display_name,
            "context_window": m.context_window,
            "role_default": m.role_default,
        }
        for m in session.exec(select(Model).where(Model.provider_id == pid)).all()
    ]
