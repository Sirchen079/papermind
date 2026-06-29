from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Model, Provider
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto


def pick_llm(session: Session, role: str) -> tuple[ProviderClient, Provider, str] | None:
    """Choose a provider + model for ``role``.

    Two model concepts only (PaperQA2's ``Settings(llm=..., embedding=...)``):
      - ``embedding``: a dedicated vector model, tagged ``embedding``. Returns
        None if none is configured — it cannot fall back to a chat model (wrong
        tool for the job).
      - every text role (chat / summarize / concept-extraction / ...): the ONE
        LLM tagged ``chat``. Summary never gets its own model; it shares the
        chat LLM. If no model is tagged ``chat``, it falls back to the first
        enabled provider's first model so a freshly-configured setup still works.

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

    # embedding needs its own model; every text role shares the single chat LLM.
    tag = "embedding" if role == "embedding" else "chat"
    model = session.exec(
        select(Model).where(Model.role_default == tag, Model.provider_id.in_(enabled_ids))
    ).first()

    if model is None:
        if role == "embedding":
            return None  # no vector model configured — don't borrow a chat model
        # last resort: first enabled provider's first model
        provider = enabled[0]
        model = session.exec(select(Model).where(Model.provider_id == provider.id)).first()
        if model is None:
            return None
    else:
        provider = next(p for p in enabled if p.id == model.provider_id)

    engine = get_engine()
    client = ProviderClient(session_factory=lambda: Session(engine), crypto=get_crypto())
    return client, provider, model.model_id
