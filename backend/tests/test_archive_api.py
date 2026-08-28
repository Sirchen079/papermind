from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper, PaperChunk, Provider


def test_archive_status_api_reports_counts(client):
    with Session(get_engine()) as session:
        session.add(Paper(source="manual", title="API Status Paper"))
        session.commit()

    res = client.get("/api/archive/status")

    assert res.status_code == 200
    body = res.json()
    assert body["database_exists"] is True
    assert body["paper_count"] == 1


def test_backup_api_creates_lists_downloads_and_rejects_traversal(client, env):
    pdf_dir = env / "data" / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
    (env / "master.key").write_bytes(b"secret-key")

    with Session(get_engine()) as session:
        session.add(Paper(source="pdf", title="API Backup Paper"))
        session.commit()

    created = client.post("/api/archive/backup")

    assert created.status_code == 200
    filename = created.json()["filename"]
    assert filename.endswith(".zip")

    listed = client.get("/api/archive/backups")
    assert listed.status_code == 200
    assert any(row["filename"] == filename for row in listed.json())

    downloaded = client.get(f"/api/archive/backups/{filename}")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")
    assert "application/zip" in downloaded.headers["content-type"]

    traversal = client.get("/api/archive/backups/..%2Fmaster.key")
    assert traversal.status_code == 404


def test_backup_verify_api_reports_backup_health(client, env):
    with Session(get_engine()) as session:
        session.add(Paper(source="manual", title="API Verify Backup Paper"))
        session.commit()

    created = client.post("/api/archive/backup")
    filename = created.json()["filename"]

    verified = client.post(f"/api/archive/backups/{filename}/verify")
    missing = client.post("/api/archive/backups/missing.zip/verify")

    assert verified.status_code == 200
    body = verified.json()
    assert body["ok"] is True
    assert body["filename"] == filename
    assert body["database"]["integrity_ok"] is True
    assert missing.status_code == 404


def test_backup_restore_guide_api_reports_offline_restore_steps(client, env):
    pdf_dir = env / "data" / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
    (env / "master.key").write_bytes(b"secret-key")

    with Session(get_engine()) as session:
        session.add(Paper(source="pdf", title="API Restore Guide Paper"))
        session.commit()

    created = client.post("/api/archive/backup")
    filename = created.json()["filename"]

    guide = client.get(f"/api/archive/backups/{filename}/restore-guide")
    missing = client.get("/api/archive/backups/missing.zip/restore-guide")

    assert guide.status_code == 200
    body = guide.json()
    assert body["filename"] == filename
    assert body["can_restore"] is True
    assert body["summary"] == "备份校验通过，可以按离线步骤恢复。"
    assert body["verification"]["ok"] is True
    assert body["paths"]["data_dir"].endswith("data")
    assert body["paths"]["database_path"].endswith(".sqlite")
    assert body["paths"]["pdf_dir"].endswith("pdfs")
    assert any("关闭正在运行的 PaperMind" in warning for warning in body["warnings"])
    assert [step["title"] for step in body["steps"]] == [
        "关闭 PaperMind",
        "保留当前数据副本",
        "解压备份包",
        "替换数据库和密钥",
        "恢复 PDF 文件",
        "重新启动并检查",
    ]
    assert missing.status_code == 404


def test_archive_json_export_api_excludes_secrets_and_embeddings(client):
    with Session(get_engine()) as session:
        provider = Provider(name="sf", type="openai_compat", api_key_encrypted="ciphertext")
        paper = Paper(source="manual", title="JSON Export Paper")
        session.add(provider)
        session.add(paper)
        session.commit()
        session.refresh(paper)
        session.add(PaperChunk(paper_id=paper.id, ordinal=0, text="chunk", embedding=b"vector"))
        session.commit()

    res = client.get("/api/archive/export/json")

    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    body = res.json()
    assert body["providers"][0]["name"] == "sf"
    assert "api_key_encrypted" not in body["providers"][0]
    assert "embedding" not in body["chunks"][0]


def test_archive_bibtex_export_api_downloads_bibtex(client):
    with Session(get_engine()) as session:
        session.add(
            Paper(
                source="manual",
                title="Graph Neural Retrieval",
                authors_json='["Grace Hopper"]',
                year=2024,
                doi="10.1234/gnr",
            )
        )
        session.commit()

    res = client.get("/api/archive/export/bibtex")

    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert "@article{hopper2024graph" in res.text
    assert "doi = {10.1234/gnr}" in res.text


def test_archive_ris_export_api_downloads_ris(client):
    with Session(get_engine()) as session:
        session.add(
            Paper(
                source="manual",
                title="Graph Neural Retrieval",
                authors_json='["Grace Hopper"]',
                year=2024,
                doi="10.1234/gnr",
            )
        )
        session.commit()

    res = client.get("/api/archive/export/ris")

    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert "papermind-library.ris" in res.headers["content-disposition"]
    assert "TY  - JOUR" in res.text
    assert "TI  - Graph Neural Retrieval" in res.text
    assert "AU  - Grace Hopper" in res.text
    assert "DO  - 10.1234/gnr" in res.text
