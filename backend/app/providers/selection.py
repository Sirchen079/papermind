from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Model, Provider
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto


def pick_llm(
    session: Session, role: str
) -> tuple[ProviderClient, Provider, str] | None:
    """Choose the first enabled provider + a model for ``role``.

    Falls back to the provider's first model if none is tagged with the role.
    Returns None when no provider/model is configured (caller degrades).

    The provider client is given a factory that opens a *fresh* session per
    call (rather than reusing the request session), so internal bookkeeping
    like token-usage recording can ``commit``/``close`` its own short-lived
    session without touching the caller's transaction — important for the
    streaming endpoint whose request session must stay open across the stream.
    """
    provider = session.exec(select(Provider).where(Provider.enabled == True)).first()  # noqa: E712
    if provider is None:
        return None
    model = session.exec(
        select(Model).where(Model.provider_id == provider.id, Model.role_default == role)
    ).first()
    if model is None:
        model = session.exec(select(Model).where(Model.provider_id == provider.id)).first()
    if model is None:
        return None
    engine = get_engine()
    client = ProviderClient(session_factory=lambda: Session(engine), crypto=get_crypto())
    return client, provider, model.model_id
