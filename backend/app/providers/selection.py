from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Model, Provider
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto


def pick_llm(
    session: Session, role: str, *, strict: bool = False
) -> tuple[ProviderClient, Provider, str] | None:
    """Choose a provider + model for ``role``.

    Prefers a model explicitly tagged with the role on ANY enabled provider, so
    e.g. a dedicated OpenAI-compatible embeddings model is picked even when the
    first provider in the list is an Anthropic chat provider. When ``strict`` is
    set (used for embeddings), there is no fallback — None is returned unless a
    role-tagged model exists. Otherwise it falls back to the first enabled
    provider's first model so a freshly-configured setup still works.

    The provider client is given a factory that opens a *fresh* session per
    call (rather than reusing the request session), so internal bookkeeping
    like token-usage recording can ``commit``/``close`` its own short-lived
    session without touching the caller's transaction — important for the
    streaming endpoint whose request session must stay open across the stream.
    """
    enabled = session.exec(select(Provider).where(Provider.enabled == True)).all()  # noqa: E712
    if not enabled:
        return None
    enabled_ids = [p.id for p in enabled]

    model = session.exec(
        select(Model).where(Model.role_default == role, Model.provider_id.in_(enabled_ids))
    ).first()
    if model is not None:
        provider = next(p for p in enabled if p.id == model.provider_id)
    elif strict:
        return None
    else:
        provider = enabled[0]
        model = session.exec(select(Model).where(Model.provider_id == provider.id)).first()
        if model is None:
            return None

    engine = get_engine()
    client = ProviderClient(session_factory=lambda: Session(engine), crypto=get_crypto())
    return client, provider, model.model_id
