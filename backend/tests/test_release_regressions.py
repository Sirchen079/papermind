import pytest
pytestmark=pytest.mark.usefixtures("accept_evidence_review")

"""Reproductions from the September release acceptance report."""
import json
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Paper


def pdf_bytes(text):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return doc.tobytes()


def upload(client, data, name="paper.pdf"):
    return client.post("/api/papers/pdf", files={"file": (name, data, "application/pdf")})


def test_same_name_pdf_and_failed_import_preserve_evidence(client):
    a, b = pdf_bytes("Original evidence A"), pdf_bytes("Different evidence B")
    first = upload(client, a).json()
    second = upload(client, b).json()
    assert first["id"] != second["id"]
    assert upload(client, b"not a valid pdf").status_code == 422
    assert upload(client, b"").status_code == 422
    assert client.get(f"/api/papers/{first['id']}/file").content == a
    assert client.get(f"/api/papers/{second['id']}/file").content == b
    assert client.get("/api/papers").json()["total"] == 2
    client.patch(f"/api/papers/{first['id']}", json={"title": "Curated title", "authors": ["Ada"]})
    repeated = upload(client, a, "download.pdf").json()
    assert repeated["id"] == first["id"]
    assert repeated["title"] == "Curated title"
    assert repeated["authors"] == ["Ada"]


def test_partial_bibtex_preserves_authors(client):
    first = client.post("/api/papers/bibtex", json={"bibtex": "@article{a,title={A study},author={Ada and Bo},year={2024}}"}).json()[0]
    second = client.post("/api/papers/bibtex", json={"bibtex": "@article{a,title={A study},year={2024}}"}).json()[0]
    assert second["id"] == first["id"]
    assert second["authors"] == ["Ada", "Bo"]


@pytest.mark.parametrize("kind", ["bibtex", "ris"])
def test_invalid_citation_import_is_actionable_and_atomic(client, kind):
    result = client.post(f"/api/papers/{kind}", json={kind: "not a citation"})
    assert result.status_code == 422
    assert "未识别" in result.json()["detail"]
    assert client.get("/api/papers").json()["total"] == 0


def test_invalid_arxiv_never_calls_remote(client):
    with patch("app.api.papers_api.fetch_arxiv") as fetch:
        result = client.post("/api/papers/arxiv", json={"arxiv_id": "not-an-id"})
    fetch.assert_not_called()
    assert result.status_code == 422


def test_backup_is_portable_without_modifying_live_paths(client, env, monkeypatch):
    import zipfile
    from fastapi.testclient import TestClient
    from app.main import create_app
    content = pdf_bytes("Portable original")
    paper = upload(client, content).json()
    with Session(get_engine()) as session:
        original_path = session.get(Paper, paper["id"]).pdf_path
    backup = client.post("/api/archive/backup").json()
    restored = env / "moved-library"
    with zipfile.ZipFile(env / "data" / "backups" / backup["filename"]) as archive:
        archive.extractall(restored)
    with Session(get_engine()) as session:
        assert session.get(Paper, paper["id"]).pdf_path == original_path
    monkeypatch.setenv("PAPERMIND_DATA_DIR", str(restored))
    monkeypatch.setenv("PAPERMIND_DB_PATH", str(restored / "papermind.sqlite"))
    migrated = TestClient(create_app())
    assert migrated.get(f"/api/papers/{paper['id']}/file").content == content


def test_legacy_restore_rebases_only_hash_verified_pdfs(client, env):
    import hashlib
    from app.ingestion.pdf_storage import finish_restore
    root = env / "data" / "pdfs"
    root.mkdir(parents=True)
    content = pdf_bytes("Restored old format")
    (root / "legacy.pdf").write_bytes(content)
    (root / "wrong.pdf").write_bytes(b"different bytes")
    with Session(get_engine()) as session:
        good = Paper(source="pdf", pdf_path="C:/old-user/data/pdfs/legacy.pdf")
        bad = Paper(source="pdf", pdf_path="C:/old-user/data/pdfs/wrong.pdf")
        session.add_all([good, bad]); session.commit()
        ids = good.id, bad.id
    manifest = {"pdfs": {"files": [
        {"path": name, "sha256": hashlib.sha256(content).hexdigest()} for name in ["legacy.pdf", "wrong.pdf"]
    ]}}
    (env / "data" / "restore-manifest.json").write_text(json.dumps(manifest))
    finish_restore(get_engine(), env / "data")
    assert client.get(f"/api/papers/{ids[0]}/file").content == content
    assert client.get(f"/api/papers/{ids[1]}/file").status_code == 404


def test_new_model_role_switches_actual_selection(client):
    from app.providers.selection import pick_llm
    provider = client.post("/api/providers", json={"name": "qa", "type": "openai_chat"}).json()
    for name in ["old", "new"]:
        assert client.post(f"/api/providers/{provider['id']}/models", json={"model_id": name, "role_default": "chat"}).status_code == 201
    roles = [m for m in client.get("/api/models").json() if m["role_default"] == "chat"]
    assert [m["model_id"] for m in roles] == ["new"]
    with Session(get_engine()) as session:
        assert pick_llm(session, "chat")[2] == "new"


@pytest.mark.parametrize("model,reasoning", [("gpt-4o", False), ("o3-mini", True), ("custom-model-123", False)])
def test_research_parameters_follow_model_capabilities(client, model, reasoning, monkeypatch):
    from types import SimpleNamespace
    from app.models import Provider
    from app.providers.client import ProviderClient
    from app.security.crypto import get_crypto
    provider = Provider(name="qa", type="openai_chat")
    captured = {}
    def complete(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))], usage=None)
    monkeypatch.setattr("app.providers.client.litellm.completion", complete)
    pc = ProviderClient(lambda: Session(get_engine()), get_crypto())
    monkeypatch.setattr(pc, "_record_usage", lambda *args, **kwargs: None)
    pc.complete(provider, model, [{"role": "user", "content": "test"}], "research", reasoning_effort="low")
    assert ("reasoning_effort" in captured) == reasoning


@pytest.mark.parametrize("suffix", ["messages", "messages/stream"])
def test_reopened_paper_chat_and_manual_skill_are_grounded(client, suffix):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.providers.client import ToolTurn
    pid = client.post("/api/papers/manual", json={"title": "Grounded paper"}).json()["id"]
    provider = client.post("/api/providers", json={"name": "qa", "type": "openai_chat"}).json()["id"]
    client.post(f"/api/providers/{provider}/models", json={"model_id": "gpt-4o", "role_default": "chat"})
    skill = client.post("/api/skills", json={"name": "Manual test", "type": "instruction", "trigger": "manual", "body": "MANUAL_BODY_MARKER"}).json()["id"]
    cid = client.post("/api/chat/conversations", json={"paper_id": pid}).json()["id"]
    reopened = TestClient(create_app())
    detail = reopened.get(f"/api/chat/conversations/{cid}").json()
    assert detail["paper_id"] == pid and detail["paper_title"] == "Grounded paper"
    captured = []
    def complete(provider, model, messages, request_kind, **kwargs):
        captured.append(messages)
        return ToolTurn("answer", [], 1, 1, 2)
    with patch("app.providers.client.ProviderClient.complete_with_tools", side_effect=complete):
        assert reopened.post(f"/api/chat/conversations/{cid}/{suffix}", json={"content": "hello", "skill_ids": [skill]}).status_code == 200
        assert "Grounded paper" in captured[-1][-1]["content"]
        assert "MANUAL_BODY_MARKER" in captured[-1][-1]["content"]
        reopened.patch(f"/api/chat/conversations/{cid}", json={"paper_id": None})
        assert reopened.post(f"/api/chat/conversations/{cid}/{suffix}", json={"content": "next"}).status_code == 200
        # History retains its snapshot, but the new turn has neither manual skill nor paper binding.
        assert "MANUAL_BODY_MARKER" not in captured[-1][-1]["content"]
        assert "[论文上下文]" not in captured[-1][-1]["content"]
        assert reopened.get(f"/api/chat/conversations/{cid}").json()["paper_id"] is None
        before = reopened.get(f"/api/chat/conversations/{cid}").json()["messages"]
        bad = reopened.post(f"/api/chat/conversations/{cid}/{suffix}", json={"content": "bad", "skill_ids": [9999]})
        assert bad.status_code == 422
        assert reopened.get(f"/api/chat/conversations/{cid}").json()["messages"] == before


@pytest.mark.parametrize("role,status", [("basis", 404), ("invalid", 422)])
def test_failed_idea_creation_has_no_partial_rows(client, role, status):
    result = client.post("/api/ideas", json={"title": "failed", "papers": [{"paper_id": 9999, "role": role}]})
    assert result.status_code == status
    assert client.get("/api/ideas").json() == []


def test_experiment_log_timestamps_have_utc_offset(client):
    project = client.post("/api/thesis/projects", json={"name": "QA"}).json()["id"]
    experiment = client.post("/api/experiments", json={"name": "QA", "project_id": project}).json()["id"]
    response = client.post(f"/api/experiments/{experiment}/logs", json={"content": "new log"})
    assert response.json()["created_at"].endswith("+00:00")
    assert client.get(f"/api/experiments/{experiment}/logs").json()[0]["created_at"].endswith("+00:00")


def test_frozen_restore_guide_matches_optional_key(client, monkeypatch):
    filename = client.post("/api/archive/backup").json()["filename"]
    monkeypatch.setattr("app.paths.is_frozen", lambda: True)
    guide = client.get(f"/api/archive/backups/{filename}/restore-guide").json()
    text = json.dumps(guide, ensure_ascii=False)
    assert "start.ps1" not in text
    assert "PaperMind.exe" in text
    assert "本备份不含 master.key" in text
    assert "restore.ps1" in text and "-ApplicationDir" in text


def test_related_rate_limit_preserves_retry_information(client):
    import httpx
    from app.knowledge.recommend import OPENALEX
    pid = client.post("/api/papers/manual", json={"title": "QA"}).json()["id"]
    response = httpx.Response(429, headers={"Retry-After": "35"}, request=httpx.Request("GET", OPENALEX))
    with patch("app.knowledge.recommend.httpx.get", return_value=response):
        result = client.get(f"/api/papers/{pid}/related")
    assert result.status_code == 503
    assert result.headers["Retry-After"] == "35"
    assert "稍后重试" in result.json()["detail"]


@pytest.mark.parametrize("code,exit_code,expected", [
    ("print('工具输出：中文成功')", 0, "工具输出：中文成功"),
    ("raise RuntimeError('QA failure')", 1, "QA failure"),
    ("import sys; sys.exit(7)", 7, ""),
])
def test_windowed_skill_worker_captures_results(tmp_path, code, exit_code, expected):
    from app.skills.worker import run_script
    script = tmp_path / "skill.py"
    script.write_text(code, encoding="utf-8")
    assert run_script(str(script)) == exit_code
    result = (tmp_path / ("stdout.txt" if exit_code == 0 else "stderr.txt")).read_text(encoding="utf-8")
    assert expected in result


def test_conversation_migration_preserves_history_and_deleted_id_high_water(env):
    import sqlite3
    from contextlib import closing
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from app import paths
    from app.main import create_app
    database = env / "test.sqlite"
    cfg = Config(str(paths.alembic_ini()))
    cfg.set_main_option("script_location", str(paths.migrations_dir()))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(cfg, "d1a7e3f902bc")
    with closing(sqlite3.connect(database)) as db:
        for cid in [4, 7]:
            db.execute("INSERT INTO conversation (id,title,created_at,updated_at) VALUES (?, 'existing', '2026-09-09', '2026-09-09')", (cid,))
        db.execute("DELETE FROM conversation WHERE id=7")
        db.execute("INSERT INTO message (conversation_id,role,content,created_at) VALUES (4,'user','retained history','2026-09-09')")
        db.commit()
    upgraded = TestClient(create_app())
    assert upgraded.get("/api/chat/conversations/4").json()["messages"][0]["content"] == "retained history"
    assert upgraded.post("/api/chat/conversations").json()["id"] > 7
