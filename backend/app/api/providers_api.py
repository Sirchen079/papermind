import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Model, Provider
from app.models.base import utcnow
from app.providers.client import ProviderClient
from app.providers import shared
from app.providers.routing import ProviderType
from app.security.crypto import get_crypto
from app.security.url_guard import ensure_http_url

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
    unavailable=False
    if p.shared_connection_id:
        try:p,_=shared.resolve(p)
        except LookupError:unavailable=True
    return {
        "id": p.id,
        "name": p.name,
        "type": p.type,
        "base_url": p.base_url,
        "enabled": p.enabled and not unavailable,
        "shared_connection_id":p.shared_connection_id,
        "shared_unavailable":unavailable,
    }


def _client(session: Session) -> ProviderClient:
    return ProviderClient(session_factory=lambda: session, crypto=get_crypto())


def _validate_base_url(base_url: str) -> None:
    """Reject non-http(s) base URLs (SSRF hardening); local hosts stay allowed."""
    try:
        ensure_http_url(base_url)
    except ValueError as exc:
        raise HTTPException(422, "base_url must be an http(s) URL") from exc


@router.get("/providers")
def list_providers(session: Session = Depends(get_session)) -> list[dict]:
    return [_public(p) for p in session.exec(select(Provider).where(Provider.is_deleted==False)).all()]


@router.post("/providers")
def create_provider(body: ProviderIn, session: Session = Depends(get_session)) -> dict:
    crypto = get_crypto()
    if body.base_url is not None:
        _validate_base_url(body.base_url)
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
    if p is None or p.is_deleted:
        raise HTTPException(404, "provider not found")
    if p.shared_connection_id and any(value is not None for value in (body.name,body.base_url,body.api_key)):
        raise HTTPException(409,'此连接使用共享配置。请编辑共享连接，或先转为项目专用连接。')
    if body.name is not None:
        p.name = body.name
    if body.base_url is not None:
        _validate_base_url(body.base_url)
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
    # Retain the identity for historical and still-running usage writes.
    p.enabled=False
    p.is_deleted=True
    p.api_key_encrypted=None
    p.extra_headers_json=None
    p.shared_connection_id=None
    session.add(p)
    session.commit()


@router.post("/providers/{pid}/models/refresh")
def refresh_models(pid: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Provider, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, "provider not found")
    try:
        actual,crypto=shared.resolve(p)
        engine=session.get_bind()
        fetched = ProviderClient(session_factory=lambda:Session(engine),crypto=crypto).list_models(actual)
    except LookupError as exc:
        raise HTTPException(409,str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"failed to fetch models: {exc}") from exc
    # Upsert by model_id so a refresh never wipes the user's role assignments.
    # The previous delete-all-then-re-add lost role_default on every refresh,
    # silently breaking chat ("no LLM configured") and RAG (embedding role
    # gone). Models that vanish from the provider are intentionally kept — a
    # stale row is harmless, and deleting would risk dropping a model the user
    # still wants (there's no delete-model UI yet to recover it).
    session.rollback()
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    p = session.get(Provider, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, 'provider not found')
    existing = {
        m.model_id: m for m in session.exec(select(Model).where(Model.provider_id == pid)).all()
    }
    now = utcnow()
    for mi in fetched:
        row = existing.get(mi.model_id)
        if row is None:
            row = Model(provider_id=pid, model_id=mi.model_id)
            session.add(row)
            existing[mi.model_id] = row
        row.display_name = mi.display_name
        # A missing upstream value must not clobber a manually configured window.
        if mi.context_window is not None:
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
            "supports_images": m.supports_images,
            "reasoning_effort": m.reasoning_effort,
            "role_default": m.role_default,
        }
        for m in session.exec(select(Model).where(Model.provider_id == pid)).all()
    ]


class ManualModelIn(BaseModel):
    model_id: str
    display_name: str | None = None
    context_window: int | None = None
    role_default: str | None = None


@router.post("/providers/{pid}/models", status_code=201)
def add_manual_model(pid: int, body: ManualModelIn, session: Session = Depends(get_session)) -> dict:
    """Add a model by id manually.

    For providers that don't expose a ``/models`` list (some ``openai_compat``
    gateways, local Ollama, …) so "Refresh models" can't discover them. The
    row is marked ``is_manual`` so a later refresh knows to leave it (and its
    role assignment) untouched.
    """
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    p = session.get(Provider, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, "provider not found")
    dup = session.exec(
        select(Model).where(Model.provider_id == pid, Model.model_id == body.model_id)
    ).first()
    if dup is not None:
        raise HTTPException(409, f"model '{body.model_id}' already exists for this provider")
    if body.role_default:
        for other in session.exec(select(Model).where(Model.role_default == body.role_default)).all():
            other.role_default = None
            session.add(other)
    if body.context_window is not None and body.context_window <= 0:
        raise HTTPException(422, "context_window 必须是正整数")
    m = Model(
        provider_id=pid,
        model_id=body.model_id,
        display_name=body.display_name,
        context_window=body.context_window,
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
        "supports_images": m.supports_images,
        "reasoning_effort": m.reasoning_effort,
        "role_default": m.role_default,
    }
