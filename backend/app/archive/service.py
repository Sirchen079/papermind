import hashlib
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from app.archive.bibtex import citekey, format_paper
from app.archive.ris import format_paper as format_ris_paper
from app.config import get_settings
from app.models import (
    AnalysisRun,
    Collection,
    CollectionPaper,
    Concept,
    Conversation,
    Message,
    Model as ProviderModel,
    Paper,
    PaperChunk,
    PaperConcept,
    PaperExcerpt,
    PaperLink,
    PaperNote,
    PaperReadingState,
    PaperTag,
    Provider,
    Project,
    ReviewMatrixEntry,
    Skill,
    Suggestion,
    Summary,
    Tag,
    TokenUsage,
    Chapter,
)
from app.models.paper import parse_authors_json


def _pdf_dir() -> Path:
    return Path(get_settings().data_dir) / "pdfs"


def _backup_dir() -> Path:
    return Path(get_settings().data_dir) / "backups"


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() and path.is_file() else 0


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count(session: Session, model: type) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())


def _active_paper_count(session: Session) -> int:
    return int(session.exec(select(func.count()).select_from(Paper).where(Paper.is_deleted == False)).one())  # noqa: E712


def _pdf_stats(pdf_dir: Path) -> tuple[int, int]:
    if not pdf_dir.is_dir():
        return 0, 0
    files = [path for path in pdf_dir.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def _latest_backup() -> dict | None:
    backup_dir = _backup_dir()
    if not backup_dir.is_dir():
        return None
    backups = [path for path in backup_dir.glob("*.zip") if path.is_file()]
    if not backups:
        return None
    latest = max(backups, key=lambda path: path.stat().st_mtime)
    return {
        "filename": latest.name,
        "size_bytes": latest.stat().st_size,
        "modified_at": datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc).isoformat(),
    }


def _sqlite_snapshot(db_path: Path, backup_dir: Path) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    handle = tempfile.NamedTemporaryFile(
        prefix=".papermind-db-",
        suffix=".sqlite",
        dir=backup_dir,
        delete=False,
    )
    snapshot_path = Path(handle.name)
    handle.close()
    source = None
    target = None
    try:
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(snapshot_path)
        source.backup(target)
    except Exception:
        snapshot_path.unlink(missing_ok=True)
        raise
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
    return snapshot_path


def _iter_pdf_files(pdf_dir: Path) -> list[Path]:
    if not pdf_dir.is_dir():
        return []
    return sorted(path for path in pdf_dir.rglob("*") if path.is_file())


def _backup_filename(now: datetime) -> str:
    return f"papermind-backup-{now.strftime('%Y%m%d-%H%M%S')}.zip"


def _unique_backup_path(backup_dir: Path, filename: str) -> Path:
    path = backup_dir / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(1, 100):
        candidate = backup_dir / f"{stem}-{idx:02d}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError("too many backups created in the same second")


def _backup_info(path: Path, manifest: dict | None = None, error: str | None = None) -> dict:
    return {
        "filename": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "manifest": manifest,
        "error": error,
    }


def _read_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("manifest.json"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sqlite_integrity_ok(data: bytes) -> tuple[bool, str | None]:
    handle = tempfile.NamedTemporaryFile(prefix=".papermind-verify-", suffix=".sqlite", delete=False)
    path = Path(handle.name)
    try:
        handle.write(data)
        handle.close()
        conn = sqlite3.connect(path)
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        finally:
            conn.close()
        messages = [str(row[0]) for row in rows]
        ok = messages == ["ok"]
        return ok, None if ok else "; ".join(messages)
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            handle.close()
        except Exception:
            pass
        path.unlink(missing_ok=True)


def _parse_json_field(value: str | None) -> object:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _dump(row: object, *, exclude: set[str] | None = None) -> dict:
    return row.model_dump(mode="json", exclude=exclude or set())  # type: ignore[attr-defined]


def _parse_tags_field(value: str | None) -> list[str]:
    parsed = _parse_json_field(value)
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _dump_tagged_row(row: object) -> dict:
    data = _dump(row)
    data["tags"] = _parse_tags_field(getattr(row, "tags_json", None))
    data.pop("tags_json", None)
    return data


def _all(session: Session, model: type) -> list:
    return session.exec(select(model)).all()


def _active_papers(session: Session) -> list[Paper]:
    return session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712


def _active_paper_ids(papers: list[Paper]) -> set[int]:
    return {paper.id for paper in papers if paper.id is not None}


def _paper_rows(session: Session, model: type, paper_ids: set[int]) -> list:
    if not paper_ids:
        return []
    return session.exec(select(model).where(model.paper_id.in_(paper_ids))).all()


def _exportable_suggestions(session: Session, paper_ids: set[int]) -> list[Suggestion]:
    rows = _all(session, Suggestion)
    return [
        row
        for row in rows
        if (row.paper_id is None or row.paper_id in paper_ids)
        and (row.related_paper_id is None or row.related_paper_id in paper_ids)
    ]


def archive_status(session: Session) -> dict:
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    db_path = Path(settings.resolved_db_path)
    master_key_path = Path(settings.resolved_master_key_path)
    pdf_dir = _pdf_dir()
    pdf_count, pdf_total_bytes = _pdf_stats(pdf_dir)

    return {
        "data_dir": str(data_dir),
        "database_path": str(db_path),
        "database_exists": db_path.exists(),
        "database_size_bytes": _file_size(db_path),
        "master_key_exists": master_key_path.exists(),
        "pdf_dir": str(pdf_dir),
        "pdf_dir_exists": pdf_dir.exists(),
        "pdf_count": pdf_count,
        "pdf_total_bytes": pdf_total_bytes,
        "paper_count": _active_paper_count(session),
        "summary_count": _count(session, Summary),
        "concept_count": _count(session, Concept),
        "chunk_count": _count(session, PaperChunk),
        "provider_count": _count(session, Provider),
        "latest_backup": _latest_backup(),
    }


def create_backup(session: Session) -> dict:
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    db_path = Path(settings.resolved_db_path)
    master_key_path = Path(settings.resolved_master_key_path)
    pdf_dir = _pdf_dir()
    backup_dir = _backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    final_path = _unique_backup_path(backup_dir, _backup_filename(now))
    snapshot_path = _sqlite_snapshot(db_path, backup_dir)
    tmp_zip = final_path.with_name(f".{final_path.name}.tmp")

    try:
        pdf_files = _iter_pdf_files(pdf_dir)
        pdf_entries = []
        pdf_total_bytes = 0
        for path in pdf_files:
            size = path.stat().st_size
            pdf_total_bytes += size
            pdf_entries.append(
                {
                    "path": path.relative_to(pdf_dir).as_posix(),
                    "size_bytes": size,
                    "sha256": _sha256(path),
                }
            )

        master_key = {
            "present": master_key_path.exists(),
            "size_bytes": _file_size(master_key_path),
            "sha256": _sha256(master_key_path) if master_key_path.exists() else None,
        }
        manifest = {
            "archive_schema_version": 1,
            "archive_type": "full-backup",
            "app": "PaperMind",
            "created_at": now.isoformat(),
            "database": {
                "filename": "papermind.sqlite",
                "size_bytes": snapshot_path.stat().st_size,
                "sha256": _sha256(snapshot_path),
            },
            "master_key": master_key,
            "pdfs": {
                "count": len(pdf_entries),
                "total_bytes": pdf_total_bytes,
                "files": pdf_entries,
            },
            "paper_count": _active_paper_count(session),
            "summary_count": _count(session, Summary),
            "concept_count": _count(session, Concept),
            "chunk_count": _count(session, PaperChunk),
            "provider_count": _count(session, Provider),
        }

        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            )
            zf.write(snapshot_path, "papermind.sqlite")
            if master_key_path.exists():
                zf.write(master_key_path, "master.key")
            for path in pdf_files:
                zf.write(path, f"pdfs/{path.relative_to(pdf_dir).as_posix()}")

        tmp_zip.replace(final_path)
        return _backup_info(final_path, manifest=manifest)
    finally:
        snapshot_path.unlink(missing_ok=True)
        tmp_zip.unlink(missing_ok=True)


def list_backups() -> list[dict]:
    backup_dir = _backup_dir()
    if not backup_dir.is_dir():
        return []

    rows = []
    for path in sorted(backup_dir.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            rows.append(_backup_info(path, manifest=_read_manifest(path)))
        except (KeyError, json.JSONDecodeError, zipfile.BadZipFile, OSError) as exc:
            rows.append(_backup_info(path, error=str(exc)))
    return rows


def resolve_backup(filename: str) -> Path:
    if Path(filename).name != filename:
        raise FileNotFoundError(filename)

    backup_dir = _backup_dir().resolve()
    path = (backup_dir / filename).resolve()
    if path.parent != backup_dir or not path.is_file():
        raise FileNotFoundError(filename)
    return path


def verify_backup(filename: str) -> dict:
    path = resolve_backup(filename)
    errors: list[str] = []
    database = {"present": False, "sha256_ok": False, "integrity_ok": False}
    master_key = {"present": False, "expected": False, "sha256_ok": False}
    pdfs = {
        "expected_count": 0,
        "verified_count": 0,
        "missing_count": 0,
        "failed_count": 0,
    }
    archive_type = None

    try:
        with zipfile.ZipFile(path) as zf:
            try:
                manifest = json.loads(zf.read("manifest.json"))
            except KeyError:
                errors.append("missing manifest.json")
                manifest = {}
            except json.JSONDecodeError as exc:
                errors.append(f"invalid manifest.json: {exc}")
                manifest = {}

            archive_type = manifest.get("archive_type")
            names = set(zf.namelist())
            db_meta = manifest.get("database") if isinstance(manifest.get("database"), dict) else {}
            db_name = db_meta.get("filename") or "papermind.sqlite"
            if db_name not in names:
                errors.append(f"missing {db_name}")
            else:
                db_bytes = zf.read(db_name)
                database["present"] = True
                expected_sha = db_meta.get("sha256")
                database["sha256_ok"] = bool(expected_sha and _sha256_bytes(db_bytes) == expected_sha)
                if not database["sha256_ok"]:
                    errors.append(f"sha256 mismatch: {db_name}")
                integrity_ok, integrity_error = _sqlite_integrity_ok(db_bytes)
                database["integrity_ok"] = integrity_ok
                if not integrity_ok:
                    errors.append(f"sqlite integrity failed: {integrity_error}")

            mk_meta = manifest.get("master_key") if isinstance(manifest.get("master_key"), dict) else {}
            master_key["expected"] = bool(mk_meta.get("present"))
            if master_key["expected"]:
                if "master.key" not in names:
                    errors.append("missing master.key")
                else:
                    mk_bytes = zf.read("master.key")
                    master_key["present"] = True
                    expected_sha = mk_meta.get("sha256")
                    master_key["sha256_ok"] = bool(expected_sha and _sha256_bytes(mk_bytes) == expected_sha)
                    if not master_key["sha256_ok"]:
                        errors.append("sha256 mismatch: master.key")

            pdf_meta = manifest.get("pdfs") if isinstance(manifest.get("pdfs"), dict) else {}
            pdf_entries = pdf_meta.get("files") if isinstance(pdf_meta.get("files"), list) else []
            pdfs["expected_count"] = len(pdf_entries)
            for entry in pdf_entries:
                if not isinstance(entry, dict):
                    pdfs["failed_count"] += 1
                    errors.append("invalid pdf manifest entry")
                    continue
                rel = str(entry.get("path") or "")
                zip_name = f"pdfs/{rel}"
                if not rel or zip_name not in names:
                    pdfs["missing_count"] += 1
                    errors.append(f"missing {zip_name}")
                    continue
                expected_sha = entry.get("sha256")
                if expected_sha and _sha256_bytes(zf.read(zip_name)) == expected_sha:
                    pdfs["verified_count"] += 1
                else:
                    pdfs["failed_count"] += 1
                    errors.append(f"sha256 mismatch: {zip_name}")
    except zipfile.BadZipFile as exc:
        errors.append(f"invalid zip file: {exc}")

    return {
        "ok": not errors,
        "filename": path.name,
        "archive_type": archive_type,
        "database": database,
        "master_key": master_key,
        "pdfs": pdfs,
        "errors": errors,
    }


def restore_guide(filename: str) -> dict:
    verification = verify_backup(filename)
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    db_path = Path(settings.resolved_db_path)
    master_key_path = Path(settings.resolved_master_key_path)
    pdf_dir = _pdf_dir()
    backup_path = resolve_backup(filename)
    can_restore = verification["ok"] and verification["archive_type"] == "full-backup"

    warnings = [
        "恢复前必须关闭正在运行的 PaperMind，避免数据库仍被占用或写入。",
        "恢复会用备份包中的数据库、master.key 和 PDF 文件覆盖当前数据，请先复制一份当前 data 目录。",
        "备份包包含本地加密主密钥 master.key，请只在可信设备上解压和保存。",
    ]
    if not can_restore:
        warnings.insert(0, "当前备份未通过校验，不建议用于恢复。")

    return {
        "filename": verification["filename"],
        "can_restore": can_restore,
        "summary": "备份校验通过，可以按离线步骤恢复。" if can_restore else "备份校验未通过，请先更换备份或重新创建备份。",
        "paths": {
            "backup_path": str(backup_path),
            "data_dir": str(data_dir),
            "database_path": str(db_path),
            "master_key_path": str(master_key_path),
            "pdf_dir": str(pdf_dir),
        },
        "warnings": warnings,
        "steps": [
            {
                "title": "关闭 PaperMind",
                "detail": "关闭浏览器中的应用页面，并停止正在运行的 start.ps1 / uvicorn 服务。",
            },
            {
                "title": "保留当前数据副本",
                "detail": f"复制当前数据目录：{data_dir}，保存为带日期的副本，方便回退。",
            },
            {
                "title": "解压备份包",
                "detail": f"把 {backup_path.name} 解压到一个临时目录，确认其中有 manifest.json、papermind.sqlite、master.key 和 pdfs/。",
            },
            {
                "title": "替换数据库和密钥",
                "detail": f"将解压出的 papermind.sqlite 覆盖到 {db_path}，将 master.key 覆盖到 {master_key_path}。",
            },
            {
                "title": "恢复 PDF 文件",
                "detail": f"将解压出的 pdfs/ 目录内容复制到 {pdf_dir}，保持子目录结构不变。",
            },
            {
                "title": "重新启动并检查",
                "detail": "运行 .\\start.ps1 -Rebuild，进入设置页检查论文数、PDF 数和最近备份状态。",
            },
        ],
        "verification": verification,
    }


def export_json(session: Session) -> dict:
    active_papers = _active_papers(session)
    active_paper_ids = _active_paper_ids(active_papers)

    papers = []
    for paper in active_papers:
        data = _dump(paper)
        data["authors"] = parse_authors_json(paper.authors_json)
        data.pop("authors_json", None)
        papers.append(data)

    summaries = []
    for summary in _paper_rows(session, Summary, active_paper_ids):
        data = _dump(summary)
        data["content"] = _parse_json_field(summary.content_json)
        data.pop("content_json", None)
        summaries.append(data)

    providers = []
    for provider in _all(session, Provider):
        data = _dump(provider, exclude={"api_key_encrypted", "extra_headers_json"})
        providers.append(data)

    suggestions = []
    for suggestion in _exportable_suggestions(session, active_paper_ids):
        data = _dump(suggestion)
        data["detail"] = _parse_json_field(suggestion.detail_json)
        data.pop("detail_json", None)
        suggestions.append(data)

    messages = []
    for message in _all(session, Message):
        data = _dump(message)
        data["sources"] = _parse_json_field(message.sources_json)
        data.pop("sources_json", None)
        messages.append(data)

    skills = []
    for skill in _all(session, Skill):
        data = _dump(skill)
        data["keywords"] = _parse_json_field(skill.keywords_json) or []
        data.pop("keywords_json", None)
        skills.append(data)

    chunks = []
    for chunk in _paper_rows(session, PaperChunk, active_paper_ids):
        chunks.append(_dump(chunk, exclude={"embedding"}))

    paper_concepts = _paper_rows(session, PaperConcept, active_paper_ids)
    concept_ids = {link.concept_id for link in paper_concepts if link.concept_id is not None}
    concepts = (
        session.exec(select(Concept).where(Concept.id.in_(concept_ids))).all()
        if concept_ids
        else []
    )

    return {
        "archive_schema_version": 1,
        "archive_type": "metadata-export",
        "app": "PaperMind",
        "exported_at": _utc_iso(),
        "papers": papers,
        "summaries": summaries,
        "concepts": [_dump(row) for row in concepts],
        "paper_concepts": [_dump(row) for row in paper_concepts],
        "analysis_runs": [_dump(row) for row in _paper_rows(session, AnalysisRun, active_paper_ids)],
        "chunks": chunks,
        "providers": providers,
        "models": [_dump(row) for row in _all(session, ProviderModel)],
        "suggestions": suggestions,
        "conversations": [_dump(row) for row in _all(session, Conversation)],
        "messages": messages,
        "usage": [_dump(row) for row in _all(session, TokenUsage)],
        "skills": skills,
        "reading_states": [_dump(row) for row in _paper_rows(session, PaperReadingState, active_paper_ids)],
        "paper_notes": [_dump_tagged_row(row) for row in _paper_rows(session, PaperNote, active_paper_ids)],
        "paper_excerpts": [_dump_tagged_row(row) for row in _paper_rows(session, PaperExcerpt, active_paper_ids)],
        "review_matrix_entries": [_dump(row) for row in _paper_rows(session, ReviewMatrixEntry, active_paper_ids)],
        "projects": [_dump(row) for row in _all(session, Project)],
        "chapters": [_dump(row) for row in _all(session, Chapter)],
        "paper_links": [_dump(row) for row in _paper_rows(session, PaperLink, active_paper_ids)],
        "tags": [_dump(row) for row in _all(session, Tag)],
        "paper_tags": [_dump(row) for row in _paper_rows(session, PaperTag, active_paper_ids)],
        "collections": [_dump(row) for row in _all(session, Collection)],
        "collection_papers": [
            _dump(row) for row in _paper_rows(session, CollectionPaper, active_paper_ids)
        ],
    }


def export_bibtex(session: Session) -> str:
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    seen: dict[str, int] = {}
    entries = []
    for paper in papers:
        base_key = citekey(paper)
        count = seen.get(base_key, 0)
        seen[base_key] = count + 1
        key = base_key if count == 0 else f"{base_key}{count + 1}"
        entries.append(format_paper(paper, key))
    return "\n\n".join(entries) + ("\n" if entries else "")


def export_ris(session: Session) -> str:
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    entries = [format_ris_paper(paper) for paper in papers]
    return "\n\n".join(entries) + ("\n" if entries else "")
