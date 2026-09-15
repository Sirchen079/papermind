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


def _build_backup_zip(
    tmp_path: Path,
    *,
    backup_name: str = "papermind-backup-test.zip",
    mutate_manifest=None,
    extra_pdfs: dict[str, bytes] | None = None,
) -> Path:
    """Build a restore backup zip from a freshly created source data set.

    ``mutate_manifest`` optionally tampers with the manifest before it is
    zipped (simulating a corrupted/malicious backup). ``extra_pdfs`` adds
    archive entries under ``pdfs/`` that the manifest does not list.
    """
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
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    backup = tmp_path / backup_name
    with zipfile.ZipFile(backup, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.write(db, "papermind.sqlite")
        zf.write(key, "master.key")
        zf.write(pdf, "pdfs/paper.pdf")
        for name, payload in (extra_pdfs or {}).items():
            zf.writestr(f"pdfs/{name}", payload)
    return backup


def _create_restore_backup(tmp_path: Path) -> Path:
    return _build_backup_zip(tmp_path)


@pytest.mark.skipif(shutil.which('powershell') is None, reason='PowerShell is required')
def test_restore_failure_after_replacement_rolls_back_database_key_and_pdfs(tmp_path):
    backup=_create_restore_backup(tmp_path)
    target=tmp_path/'rollback-target';target.mkdir()
    with sqlite3.connect(target/'papermind.sqlite') as db:
        db.execute('CREATE TABLE old_data(value TEXT)');db.execute("INSERT INTO old_data VALUES('Keep original')")
    db.close()  # sqlite3 context managers commit, but do not close the handle.
    (target/'master.key').write_bytes(b'original-key')
    (target/'pdfs').mkdir();(target/'pdfs'/'old.pdf').write_bytes(b'original-pdf')
    wrapper=tmp_path/'fault.ps1'
    # Fail only the final marker publication, after DB, key and PDFs changed.
    # The production restore code has no fault injection branch.
    wrapper.write_text('''param($Script,$Backup,$Target)
$global:RestoreTestFailed=$false
function Copy-Item {
  [CmdletBinding()] param([string[]]$LiteralPath,[string]$Destination,[switch]$Recurse,[switch]$Force)
  if ((Split-Path -Leaf $Destination) -eq 'restore-manifest.json' -and -not $global:RestoreTestFailed) {
    $global:RestoreTestFailed=$true
    throw 'Synthetic marker write failure'
  }
  Microsoft.PowerShell.Management\\Copy-Item @PSBoundParameters
}
& $Script -Backup $Backup -DataDir $Target -Apply
''',encoding='utf-8')
    result=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(wrapper),'-Script',str(ROOT/'restore.ps1'),'-Backup',str(backup),'-Target',str(target)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=35)
    assert result.returncode!=0 and 'Synthetic marker write failure' in result.stderr
    with sqlite3.connect(target/'papermind.sqlite') as db:
        assert db.execute('SELECT value FROM old_data').fetchone()[0]=='Keep original'
    assert (target/'master.key').read_bytes()==b'original-key'
    assert (target/'pdfs'/'old.pdf').read_bytes()==b'original-pdf'
    assert not (target/'pdfs'/'paper.pdf').exists()
    assert not (target/'restore-manifest.json').exists()
    assert list(tmp_path.glob('data.before-restore-*'))


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


def _mutate_schema_version_to_2(manifest: dict) -> None:
    manifest["archive_schema_version"] = 2


def _mutate_database_sha256_to_null(manifest: dict) -> None:
    manifest["database"]["sha256"] = None


def _mutate_pdf_path_to_traversal(manifest: dict) -> None:
    manifest["pdfs"]["files"][0]["path"] = "../evil.pdf"


MALICIOUS_BACKUP_CASES = [
    pytest.param(
        {"mutate_manifest": _mutate_schema_version_to_2},
        "archive_schema_version",
        id="manifest-schema-version-2",
    ),
    pytest.param(
        {"mutate_manifest": _mutate_database_sha256_to_null},
        "sha256 is missing",
        id="database-sha256-null",
    ),
    pytest.param(
        {"mutate_manifest": _mutate_pdf_path_to_traversal},
        "must not contain '..'",
        id="pdf-path-traversal",
    ),
    pytest.param(
        {"extra_pdfs": {"smuggled.pdf": b"%PDF-1.4 smuggled"}},
        "does not match manifest",
        id="extra-pdf-not-in-manifest",
    ),
]


def _assert_data_dir_untouched(data_dir: Path) -> None:
    if not data_dir.exists():
        return
    assert not (data_dir / "papermind.sqlite").exists()
    assert not (data_dir / "master.key").exists()
    assert not any((data_dir / "pdfs").rglob("*"))


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
@pytest.mark.parametrize(("mutation", "expected_error_keyword"), MALICIOUS_BACKUP_CASES)
def test_restore_script_rejects_malicious_backup_dry_run(tmp_path, mutation, expected_error_keyword):
    backup = _build_backup_zip(
        tmp_path,
        backup_name="papermind-backup-malicious.zip",
        **mutation,
    )
    data_dir = tmp_path / "data"

    result = _run_restore("-Backup", str(backup), "-DataDir", str(data_dir))

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert expected_error_keyword in output
    assert "Restore preflight passed" not in output
    _assert_data_dir_untouched(data_dir)


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


def test_explicit_directory_ignores_other_project_environment_paths(tmp_path, monkeypatch):
    backup = _create_restore_backup(tmp_path)
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'db.sqlite').write_bytes(b'Keep other project')
    (other / 'key').write_bytes(b'Keep other key')
    monkeypatch.setenv('PAPERMIND_DB_PATH', str(other / 'db.sqlite'))
    monkeypatch.setenv('PAPERMIND_MASTER_KEY_PATH', str(other / 'key'))
    target = tmp_path / 'target'
    result = _run_restore('-Backup', str(backup), '-DataDir', str(target), '-Apply')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (other / 'db.sqlite').read_bytes() == b'Keep other project'
    assert (other / 'key').read_bytes() == b'Keep other key'
    assert (target / 'master.key').read_text() == 'restored-key'


def test_restore_refuses_running_app_lease_and_succeeds_when_closed(tmp_path):
    from app.workspaces.runtime_lease import RuntimeLease
    backup = _create_restore_backup(tmp_path)
    root = tmp_path / 'app'
    target = root / 'workspaces' / ('a' * 32)
    target.mkdir(parents=True)
    (root / 'workspaces.sqlite').write_bytes(b'Registry fixture')
    (target / 'papermind.sqlite').write_bytes(b'Keep existing database')
    lease = RuntimeLease(root)
    second = RuntimeLease(root)  # Multiple live read leases coexist.
    try:
        result = _run_restore('-Backup', str(backup), '-DataDir', str(target), '-Apply')
        assert result.returncode != 0
        assert 'PaperMind is running' in result.stdout + result.stderr
        assert (target / 'papermind.sqlite').read_bytes() == b'Keep existing database'
    finally:
        lease.close(); second.close()
    result = _run_restore('-Backup', str(backup), '-DataDir', str(target), '-Apply')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / 'workspaces.sqlite').read_bytes() == b'Registry fixture'


def test_restore_refuses_legacy_open_sqlite_handle(tmp_path):
    backup = _create_restore_backup(tmp_path)
    target = tmp_path / 'target'
    target.mkdir()
    db = sqlite3.connect(target / 'papermind.sqlite')
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE original(value TEXT)')
        db.execute("INSERT INTO original VALUES('Keep running data')")
        db.commit()
        result = _run_restore('-Backup', str(backup), '-DataDir', str(target), '-Apply')
        assert result.returncode != 0
        assert 'still open' in result.stdout + result.stderr
        assert db.execute('SELECT value FROM original').fetchone()[0] == 'Keep running data'
    finally:
        db.close()


def test_offline_restore_preserves_then_removes_stale_sidecars(tmp_path):
    backup = _create_restore_backup(tmp_path)
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'papermind.sqlite').write_bytes(b'Old crashed database')
    for suffix in ('-wal', '-shm', '-journal'):
        (target / ('papermind.sqlite' + suffix)).write_bytes(b'Old sidecar ' + suffix.encode())
    result = _run_restore('-Backup', str(backup), '-DataDir', str(target), '-Apply')
    assert result.returncode == 0, result.stdout + result.stderr
    before = next(tmp_path.glob('data.before-restore-*'))
    for suffix in ('-wal', '-shm', '-journal'):
        assert not (target / ('papermind.sqlite' + suffix)).exists()
        assert (before / ('papermind.sqlite' + suffix)).read_bytes().startswith(b'Old sidecar')
    with sqlite3.connect(target / 'papermind.sqlite') as restored:
        assert restored.execute('SELECT title FROM paper').fetchone()[0] == 'Restored Paper'
