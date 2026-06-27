from datetime import date

from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Model, Provider, Setting, TokenUsage


def test_setting_roundtrip(tmp_path):
    eng = make_engine(tmp_path / "m.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Setting(key="theme", value="dark"))
        s.commit()
        row = s.exec(select(Setting).where(Setting.key == "theme")).one()
        assert row.value == "dark"


def test_provider_and_model_roundtrip(tmp_path):
    eng = make_engine(tmp_path / "m.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        p = Provider(
            name="openai",
            type="openai_chat",
            base_url="https://api.openai.com/v1",
            api_key_encrypted="enc",
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Model(provider_id=p.id, model_id="gpt-4o", display_name="GPT-4o", context_window=128000))
        s.commit()
        m = s.exec(select(Model).where(Model.model_id == "gpt-4o")).one()
        assert m.provider_id == p.id


def test_token_usage_persists(tmp_path):
    eng = make_engine(tmp_path / "m.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        p = Provider(name="openai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(
            TokenUsage(
                provider_id=p.id,
                model="gpt-4o",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                request_kind="chat",
                day=date(2026, 6, 28),
            )
        )
        s.commit()
        assert s.exec(select(TokenUsage)).first() is not None
