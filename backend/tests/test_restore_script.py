import hashlib
import json
import shutil
import sqlite3
import subprocess
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _create_restore_backup(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    db = source / "papermind.sqlite"
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE paper (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO paper (title) VALUES ('Restored Paper')")
        conn.commit()
    finally:
        conn.close()
    key = source / "master.key"
    key.write_text("restored-key", encoding="utf-8")
    pdf = source / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 restored")
    manifest = {
        "archive_schema_version": 1,
        "archive_type": "full-backup",
        "database": {
            "filename": "papermind.sqlite",
            "sha256": _sha256(db),
        },
        "master_key": {
            "present": True,
            "sha256": _sha256(key),
        },
        "pdfs": {
            "files": [
                {
                    "path": "paper.pdf",
                    "sha256": _sha256(pdf),
                }
            ]
        },
    }
    backup = tmp_path / "papermind-backup-test.zip"
    with zipfile.ZipFile(backup, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.write(db, "papermind.sqlite")
        zf.write(key, "master.key")
        zf.write(pdf, "pdfs/paper.pdf")
    return backup


def _run_restore(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "restore.ps1"),
            *args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=35,
    )


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_restore_script_dry_run_verifies_backup_without_writing(tmp_path):
    backup = _create_restore_backup(tmp_path)
    data_dir = tmp_path / "data"

    result = _run_restore("-Backup", str(backup), "-DataDir", str(data_dir))

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "Restore preflight passed" in output
    assert "No -Apply flag" in output
    assert not (data_dir / "papermind.sqlite").exists()
    assert not (data_dir / "master.key").exists()
    assert not (data_dir / "pdfs" / "paper.pdf").exists()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_restore_script_apply_creates_current_copy_and_restores_files(tmp_path):
    backup = _create_restore_backup(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "papermind.sqlite").write_text("old-db", encoding="utf-8")
    (data_dir / "master.key").write_text("old-key", encoding="utf-8")
    (data_dir / "pdfs").mkdir()
    (data_dir / "pdfs" / "old.pdf").write_bytes(b"old")

    result = _run_restore("-Backup", str(backup), "-DataDir", str(data_dir), "-Apply")

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "Restore complete" in output
    assert (data_dir / "papermind.sqlite").exists()
    assert (data_dir / "master.key").read_text(encoding="utf-8") == "restored-key"
    assert (data_dir / "pdfs" / "paper.pdf").read_bytes() == b"%PDF-1.4 restored"
    assert not (data_dir / "pdfs" / "old.pdf").exists()
    backups = list(tmp_path.glob("data.before-restore-*"))
    assert len(backups) == 1
    assert (backups[0] / "master.key").read_text(encoding="utf-8") == "old-key"
