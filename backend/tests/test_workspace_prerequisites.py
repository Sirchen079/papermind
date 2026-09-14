"""Regressions that must hold before introducing independent databases."""
from sqlmodel import SQLModel, Session

from app.db.engine import make_engine
from app.models import Model, Provider
from app.providers.selection import pick_llm


def test_model_client_bookkeeping_uses_callers_database(env):
    engine = make_engine(env / 'other-research.sqlite')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        provider = Provider(name='Synthetic', type='openai_compat')
        session.add(provider)
        session.commit()
        session.add(Model(provider_id=provider.id, model_id='synthetic', role_default='chat'))
        session.commit()
        client, _, _ = pick_llm(session, 'chat')
    # The originating request session has closed; bookkeeping still belongs here.
    with client._session_factory() as usage_session:
        assert usage_session.get_bind() is engine
