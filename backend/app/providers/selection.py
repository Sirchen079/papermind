from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Model, Provider
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto

# "Just text generation" roles — all of these can be served by ONE LLM. ``chat``
# is the canonical default LLM; the others fall back to a chat-tagged model so a
# single model handles conversation, ingest-time summarize, and concept
# extraction alike (the PaperQA2 ``Settings(llm=..., embedding=...)`` model).
LLM_ROLES = {"chat", "summary", "extraction", "deep"}


def pick_llm(
    session: Session, role: str, *, strict: bool = False
) -> tuple[ProviderClient, Provider, str] | None:
    """Choose a provider + model for ``role``.

    Resolution order for an LLM role (chat/summary/extraction/deep):
      1. a model explicitly tagged with that exact role;
      2. a model tagged ``chat`` (the default LLM) — so one model serves every
         text task;
      3. the first enabled provider's first model (last-resort fallback).
    ``embedding`` is strict: only an exact ``embedding``-tagged model on an
    enabled provider qualifies; None otherwise (it cannot fall back to a chat
    model — wrong tool for the job).

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

    # 1) exact role match
    model = session.exec(
        select(Model).where(Model.role_default == role, Model.provider_id.in_(enabled_ids))
    ).first()
    # 2) an LLM role with no exact match reuses the default LLM (chat-tagged).
    #    Skipped under `strict` (strict = exact match only, no fallback of any kind).
    if model is None and not strict and role in LLM_ROLES and role != "chat":
        model = session.exec(
            select(Model).where(Model.role_default == "chat", Model.provider_id.in_(enabled_ids))
        ).first()

    if model is not None:
        provider = next(p for p in enabled if p.id == model.provider_id)
    elif strict:
        return None
    else:
        # 3) last resort: first enabled provider's first model
        provider = enabled[0]
        model = session.exec(select(Model).where(Model.provider_id == provider.id)).first()
        if model is None:
            return None

    engine = get_engine()
    client = ProviderClient(session_factory=lambda: Session(engine), crypto=get_crypto())
    return client, provider, model.model_id
