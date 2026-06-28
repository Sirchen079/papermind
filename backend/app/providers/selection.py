from sqlmodel import Session, select

from app.models import Model, Provider
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto


def pick_llm(
    session: Session, role: str
) -> tuple[ProviderClient, Provider, str] | None:
    """Choose the first enabled provider + a model for ``role``.

    Falls back to the provider's first model if none is tagged with the role.
    Returns None when no provider/model is configured (caller degrades).
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
    client = ProviderClient(session_factory=lambda: session, crypto=get_crypto())
    return client, provider, model.model_id
