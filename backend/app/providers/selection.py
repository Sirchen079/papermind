from sqlmodel import Session, select

from app.models import Model, Provider
from app.providers.client import ProviderClient
from app.providers.shared import resolve


def pick_llm(session: Session, role: str) -> tuple[ProviderClient, Provider, str] | None:
    """Choose a provider + model for ``role``.

    Two model concepts only (PaperQA2's ``Settings(llm=..., embedding=...)``):
      - ``embedding``: a dedicated vector model, tagged ``embedding``. Returns
        None if none is configured — it cannot fall back to a chat model (wrong
        tool for the job).
      - every text role (chat / summarize / concept-extraction / ...): the ONE
        LLM tagged ``chat``. Summary never gets its own model; it shares the
        chat LLM. If no model is tagged ``chat``, it falls back to the first
        available unassigned/text model so a freshly-configured setup still works.

    The provider client is given a factory that opens a *fresh* session per
    call (rather than reusing the request session), so internal bookkeeping
    like token-usage recording can ``commit``/``close`` its own short-lived
    session without touching the caller's transaction — important for the
    streaming endpoint whose request session must stay open across the stream.
    """
    resolved={}
    enabled=[]
    for p in session.exec(select(Provider).where(Provider.enabled==True,Provider.is_deleted==False)).all():
        try:actual,crypto=resolve(p)
        except LookupError:continue
        if actual.enabled:
            enabled.append(actual);resolved[actual.id]=crypto
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
        # A partially configured connection must not hide usable models on a
        # later connection. Explicit vector assignments are never text fallbacks.
        model = session.exec(select(Model).where(
            Model.provider_id.in_(enabled_ids),
            (Model.role_default.is_(None)) | (Model.role_default != 'embedding'),
        ).order_by(Model.provider_id, Model.id)).first()
        if model is None:
            return None
        provider = next(p for p in enabled if p.id == model.provider_id)
    else:
        provider = next(p for p in enabled if p.id == model.provider_id)

    # Capture the database used to select this model. A later usage/cache write
    # must keep the caller's database even after its request session closes.
    engine = session.get_bind()
    client = ProviderClient(session_factory=lambda: Session(engine), crypto=resolved[provider.id])
    return client, provider, model.model_id
