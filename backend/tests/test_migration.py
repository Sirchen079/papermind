from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND = Path(__file__).resolve().parent.parent


def _cfg(db_path: Path) -> Config:
    c = Config(str(BACKEND / "alembic.ini"))
    c.set_main_option("script_location", str(BACKEND / "migrations"))
    c.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return c


def test_upgrade_creates_all_tables(tmp_path):
    cfg = _cfg(tmp_path / "mig.sqlite")
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{tmp_path / 'mig.sqlite'}"))
    names = set(inspector.get_table_names())
    for t in ["setting", "provider", "model", "tokenusage", "tokenusagedaily"]:
        assert t in names, f"missing table {t}"
    paper_columns = {column["name"] for column in inspector.get_columns("paper")}
    assert "citation_key" in paper_columns


def test_downgrade_clean(tmp_path):
    cfg = _cfg(tmp_path / "mig.sqlite")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    names = set(inspect(create_engine(f"sqlite:///{tmp_path / 'mig.sqlite'}")).get_table_names())
    assert {"setting", "provider", "model"}.isdisjoint(names)
