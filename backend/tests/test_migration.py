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


def test_conversation_identity_upgrade_preserves_messages_and_never_reuses_id(tmp_path):
    import sqlite3
    db = tmp_path / "conversation-upgrade.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "b9d6a2e8f013")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversation (id,title,created_at,updated_at) VALUES (41,'Existing chat','2026-09-06','2026-09-06')")
        conn.execute("INSERT INTO message (conversation_id,role,content,created_at) VALUES (41,'user','Keep this history','2026-09-06')")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert conn.execute("SELECT title FROM conversation WHERE id=41").fetchone()[0] == "Existing chat"
        assert conn.execute("SELECT content FROM message WHERE conversation_id=41").fetchone()[0] == "Keep this history"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("DELETE FROM message WHERE conversation_id=41")
        conn.execute("DELETE FROM conversation WHERE id=41")
        cursor = conn.execute("INSERT INTO conversation (title,created_at,updated_at) VALUES ('New chat','2026-09-06','2026-09-06')")
        assert cursor.lastrowid > 41


def test_upgrade_creates_all_tables(tmp_path):
    cfg = _cfg(tmp_path / "mig.sqlite")
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{tmp_path / 'mig.sqlite'}"))
    names = set(inspector.get_table_names())
    for t in ["setting", "provider", "model", "tokenusage", "tokenusagedaily"]:
        assert t in names, f"missing table {t}"
    paper_columns = {column["name"] for column in inspector.get_columns("paper")}
    assert "citation_key" in paper_columns


def test_application_upgrade_keeps_pre_schema_backup_and_existing_provider(env):
    import sqlite3
    from app.main import create_app
    db=env/'test.sqlite'
    command.upgrade(_cfg(db),'a4d1e8c093bf')
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO provider(name,type,enabled,created_at,updated_at) VALUES('Existing','openai_chat',1,'2026-09-10','2026-09-10')")
    create_app()
    backups=list((env/'data'/'backups').glob('schema-before-*.sqlite'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='a4d1e8c093bf'
        assert conn.execute('SELECT name FROM provider').fetchone()[0]=='Existing'
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT name,is_deleted,shared_connection_id FROM provider').fetchone()==('Existing',0,None)
    create_app()
    assert list((env/'data'/'backups').glob('schema-before-*.sqlite'))==backups


def test_clarification_upgrade_preserves_existing_chat_and_downgrades(tmp_path):
    import sqlite3
    db = tmp_path / "clarification-upgrade.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "f3c9d2a071be")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversation (id,title,created_at,updated_at) VALUES (1,'Existing','2026-09-10','2026-09-10')")
        conn.execute("INSERT INTO message (conversation_id,role,content,created_at) VALUES (1,'assistant','Keep original answer','2026-09-10')")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT content,clarification_json,agent_state_json FROM message").fetchone() == ("Keep original answer", None, None)
    command.downgrade(cfg, "f3c9d2a071be")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT content FROM message").fetchone()[0] == "Keep original answer"
        assert "clarification_json" not in {row[1] for row in conn.execute("PRAGMA table_info(message)")}


def test_downgrade_clean(tmp_path):
    cfg = _cfg(tmp_path / "mig.sqlite")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    names = set(inspect(create_engine(f"sqlite:///{tmp_path / 'mig.sqlite'}")).get_table_names())
    assert {"setting", "provider", "model"}.isdisjoint(names)


def test_papercitation_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "mig.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))

    assert "papercitation" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("papercitation")}
    assert {
        "id",
        "source_paper_id",
        "target_paper_id",
        "raw_ref",
        "ref_title",
        "ref_title_norm",
        "ref_doi",
        "ref_arxiv_id",
        "ref_year",
        "ref_authors_json",
        "match_status",
        "match_confidence",
        "created_at",
    } <= columns
    uniques = {
        tuple(uq["column_names"])
        for uq in inspector.get_unique_constraints("papercitation")
    }
    assert ("source_paper_id", "ref_title_norm") in uniques
    indexes = {ix["column_names"][0] for ix in inspector.get_indexes("papercitation")}
    assert {"source_paper_id", "target_paper_id", "ref_title_norm", "ref_doi", "ref_arxiv_id"} <= indexes

    # Downgrade exactly this revision (not the whole chain).
    command.downgrade(cfg, "9d2e1f3a4b5c")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    assert "papercitation" not in inspector.get_table_names()
    assert "tag" in inspector.get_table_names()  # previous revision's tables stay


def test_idea_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "mig.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))

    assert {"idea", "ideapaperlink"} <= set(inspector.get_table_names())
    idea_columns = {column["name"] for column in inspector.get_columns("idea")}
    assert {
        "id",
        "title",
        "content",
        "hypothesis",
        "status",
        "priority",
        "origin",
        "project_id",
        "is_deleted",
        "created_at",
        "updated_at",
        "closed_at",
    } <= idea_columns
    uniques = {
        tuple(uq["column_names"])
        for uq in inspector.get_unique_constraints("ideapaperlink")
    }
    assert ("idea_id", "paper_id", "role") in uniques

    command.downgrade(cfg, "b8f4a2d6c9e1")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    assert {"idea", "ideapaperlink"}.isdisjoint(inspector.get_table_names())
    assert "papercitation" in inspector.get_table_names()  # previous revision stays


def test_radar_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "mig.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))

    assert {"subscription", "radarseen"} <= set(inspector.get_table_names())
    sub_columns = {column["name"] for column in inspector.get_columns("subscription")}
    assert {
        "id",
        "name",
        "query_type",
        "query_value",
        "max_results",
        "lookback_days",
        "enabled",
        "last_run_at",
        "created_at",
    } <= sub_columns
    seen_columns = {column["name"] for column in inspector.get_columns("radarseen")}
    assert {"arxiv_id", "seen_date"} <= seen_columns
    seen_indexes = {ix["column_names"][0] for ix in inspector.get_indexes("radarseen")}
    assert "arxiv_id" in seen_indexes
    seen_pks = {column["name"] for column in inspector.get_columns("radarseen") if column["primary_key"]}
    assert seen_pks == {"arxiv_id"}  # unique by primary key

    command.downgrade(cfg, "c3a7e8f2b5d9")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    assert {"subscription", "radarseen"}.isdisjoint(inspector.get_table_names())
    assert "ideapaperlink" in inspector.get_table_names()  # previous revision stays


def test_chapterdraft_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "mig.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))

    assert "chapterdraft" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("chapterdraft")}
    assert {"id", "chapter_id", "content", "model", "created_at"} <= columns
    indexes = {ix["column_names"][0] for ix in inspector.get_indexes("chapterdraft")}
    assert "chapter_id" in indexes
    fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("chapterdraft")}
    assert "chapter" in fks

    command.downgrade(cfg, "e1a4b7c9d2f6")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    assert "chapterdraft" not in inspector.get_table_names()
    assert "subscription" in inspector.get_table_names()  # previous revision stays


def test_reader_last_page_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "mig.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))

    columns = {column["name"] for column in inspector.get_columns("paperreadingstate")}
    assert "last_page" in columns

    # Downgrade exactly this revision: the column goes away, the table stays.
    command.downgrade(cfg, "d8f3a1b2c4e5")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    columns = {column["name"] for column in inspector.get_columns("paperreadingstate")}
    assert "last_page" not in columns
    assert "paperreadingstate" in inspector.get_table_names()


def test_claim_graph_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "mig.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))

    assert {"claim", "claimrelation"} <= set(inspector.get_table_names())
    claim_columns = {column["name"] for column in inspector.get_columns("claim")}
    assert {
        "id",
        "paper_id",
        "text",
        "kind",
        "source",
        "excerpt_id",
        "is_deleted",
        "created_at",
    } <= claim_columns
    claim_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("claim")}
    assert {"paper", "paperexcerpt"} <= claim_fks
    uniques = {
        tuple(uq["column_names"])
        for uq in inspector.get_unique_constraints("claimrelation")
    }
    assert ("claim_a_id", "claim_b_id", "type") in uniques
    indexes = {ix["column_names"][0] for ix in inspector.get_indexes("claimrelation")}
    assert {"claim_a_id", "claim_b_id"} <= indexes

    command.downgrade(cfg, "b7d2e9f4c3a1")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    assert {"claim", "claimrelation"}.isdisjoint(inspector.get_table_names())
    assert "paperreadingstate" in inspector.get_table_names()  # previous revision stays


def test_experiment_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "mig.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))

    assert {"experiment", "experimentlog", "experimentpaperlink"} <= set(inspector.get_table_names())
    exp_columns = {column["name"] for column in inspector.get_columns("experiment")}
    assert {
        "id",
        "project_id",
        "idea_id",
        "name",
        "hypothesis",
        "status",
        "started_at",
        "finished_at",
        "is_deleted",
        "created_at",
        "updated_at",
    } <= exp_columns
    exp_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("experiment")}
    assert {"project", "idea"} <= exp_fks
    log_columns = {column["name"] for column in inspector.get_columns("experimentlog")}
    assert {"id", "experiment_id", "content", "created_at"} <= log_columns
    assert "updated_at" not in log_columns  # append-only timeline
    link_uniques = {
        tuple(uq["column_names"])
        for uq in inspector.get_unique_constraints("experimentpaperlink")
    }
    assert ("experiment_id", "paper_id", "role") in link_uniques
    link_indexes = {ix["column_names"][0] for ix in inspector.get_indexes("experimentpaperlink")}
    assert {"experiment_id", "paper_id"} <= link_indexes

    command.downgrade(cfg, "c4e8f1a6b9d2")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    assert {"experiment", "experimentlog", "experimentpaperlink"}.isdisjoint(
        inspector.get_table_names()
    )
    assert "claimrelation" in inspector.get_table_names()  # previous revision stays


def test_report_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / "mig.sqlite"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))

    assert "report" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("report")}
    assert {"id", "since", "until", "content", "model", "created_at"} <= columns

    command.downgrade(cfg, "f6a9c2e5b8d1")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    assert "report" not in inspector.get_table_names()
    assert "experiment" in inspector.get_table_names()  # previous revision stays
