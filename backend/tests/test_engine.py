from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.engine import make_engine, vec_available


def test_engine_enables_wal(tmp_path):
    eng = make_engine(tmp_path / "x.sqlite")
    with eng.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"
    assert isinstance(eng, Engine)


def test_vec_loader_is_callable_and_does_not_crash():
    # Availability depends on whether the bundled SQLite supports extensions.
    assert callable(vec_available)
    assert isinstance(vec_available(), bool)
