from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Model, Provider

router = APIRouter()


class ModelPatch(BaseModel):
    role_default: str | None = None
    display_name: str | None = None


@router.get("/models")
def list_models(session: Session = Depends(get_session)) -> list[dict]:
    out = []
    for m in session.exec(select(Model)).all():
        p = session.get(Provider, m.provider_id)
        out.append(
            {
                "id": m.id,
                "model_id": m.model_id,
                "display_name": m.display_name,
                "context_window": m.context_window,
                "role_default": m.role_default,
                "provider_id": m.provider_id,
                "provider_name": p.name if p else None,
            }
        )
    return out


@router.patch("/models/{mid}")
def patch_model(mid: int, body: ModelPatch, session: Session = Depends(get_session)) -> dict:
    m = session.get(Model, mid)
    if m is None:
        raise HTTPException(404, "model not found")
    if body.role_default is not None:
        new_role = body.role_default
        if new_role:
            # Enforce ONE model per role: assigning role R to this model clears R
            # from every other model. Otherwise pick_llm (which takes the first
            # match) is nondeterministic, and you can end up with two "embedding"
            # models — e.g. bge-m3 AND a reranker both tagged embedding.
            for other in session.exec(
                select(Model).where(Model.role_default == new_role, Model.id != mid)
            ).all():
                other.role_default = None
                session.add(other)
        m.role_default = new_role
    if body.display_name is not None:
        m.display_name = body.display_name
    session.add(m)
    session.commit()
    session.refresh(m)
    return {"id": m.id, "role_default": m.role_default, "display_name": m.display_name}
