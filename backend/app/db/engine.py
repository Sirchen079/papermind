from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.db import vec as _vec


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        # Best-effort sqlite-vec load: bundled SQLite on Windows often lacks
        # extension support; vector features simply stay off in that case.
        try:
            import sqlite_vec  # type: ignore

            dbapi_conn.enable_load_extension(True)
            sqlite_vec.load(dbapi_conn)
            _vec.mark_available(True)
        except Exception:  # noqa: BLE001
            _vec.mark_available(False)

    return engine


# Path-keyed cache: each distinct DB path gets its own engine. Tests use a
# unique temp path per case, so they stay isolated without an explicit reset;
# production reuses one engine for its single path.
_engines: dict[str, Engine] = {}


def get_engine() -> Engine:
    from app.config import get_settings

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key = str(settings.resolved_db_path)
    if key not in _engines:
        _engines[key] = make_engine(settings.resolved_db_path)
    return _engines[key]


def reset_engine_for_tests() -> None:
    """Drop all cached engines. Optional given the path-keyed cache."""
    _engines.clear()


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def vec_available() -> bool:
    return _vec.vec_available()
