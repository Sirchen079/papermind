import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Model, Provider
from app.models.base import utcnow
from app.providers.client import ProviderClient
from app.providers.routing import ProviderType
from app.security.crypto import get_crypto

router = APIRouter()


class ProviderIn(BaseModel):
    name: str
    type: ProviderType
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _compat_requires_base_url(self) -> "ProviderIn":
        if self.type == ProviderType.openai_compat and not self.base_url:
            raise ValueError("openai_compat provider requires base_url")
        return self


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
    try:
        fetched = _client(session).list_models(p)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"failed to fetch models: {exc}") from exc
    # Upsert by model_id so a refresh never wipes the user's role assignments.
    # The previous delete-all-then-re-add lost role_default on every refresh,
    # silently breaking chat ("no LLM configured") and RAG (embedding role
    # gone). Models that vanish from the provider are intentionally kept — a
    # stale row is harmless, and deleting would risk dropping a model the user
    # still wants (there's no delete-model UI yet to recover it).
    existing = {
        m.model_id: m for m in session.exec(select(Model).where(Model.provider_id == pid)).all()
    }
    now = utcnow()
    for mi in fetched:
        row = existing.get(mi.model_id)
        if row is None:
            row = Model(provider_id=pid, model_id=mi.model_id)
            session.add(row)
        row.display_name = mi.display_name
        row.context_window = mi.context_window
        row.fetched_at = now
        row.is_manual = False
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


class ManualModelIn(BaseModel):
    model_id: str
    display_name: str | None = None
    role_default: str | None = None


@router.post("/providers/{pid}/models", status_code=201)
def add_manual_model(pid: int, body: ManualModelIn, session: Session = Depends(get_session)) -> dict:
    """Add a model by id manually.

    For providers that don't expose a ``/models`` list (some ``openai_compat``
    gateways, local Ollama, …) so "Refresh models" can't discover them. The
    row is marked ``is_manual`` so a later refresh knows to leave it (and its
    role assignment) untouched.
    """
    p = session.get(Provider, pid)
    if p is None:
        raise HTTPException(404, "provider not found")
    dup = session.exec(
        select(Model).where(Model.provider_id == pid, Model.model_id == body.model_id)
    ).first()
    if dup is not None:
        raise HTTPException(409, f"model '{body.model_id}' already exists for this provider")
    m = Model(
        provider_id=pid,
        model_id=body.model_id,
        display_name=body.display_name,
        role_default=body.role_default,
        is_manual=True,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return {
        "id": m.id,
        "model_id": m.model_id,
        "display_name": m.display_name,
        "context_window": m.context_window,
        "role_default": m.role_default,
    }
