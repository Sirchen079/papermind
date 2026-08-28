import json

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.deps import get_session
from app.archive.service import (
    archive_status,
    create_backup,
    export_bibtex,
    export_json,
    export_ris,
    list_backups,
    resolve_backup,
    restore_guide,
    verify_backup,
)

router = APIRouter()


def _public_backup(row: dict) -> dict:
    return {
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "modified_at": row["modified_at"],
        "manifest": row.get("manifest"),
        "error": row.get("error"),
    }


@router.get("/archive/status")
def status(session: Session = Depends(get_session)) -> dict:
    return archive_status(session)


@router.post("/archive/backup")
def backup(session: Session = Depends(get_session)) -> dict:
    try:
        return _public_backup(create_backup(session))
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/archive/backups")
def backups() -> list[dict]:
    return [_public_backup(row) for row in list_backups()]


@router.post("/archive/backups/{filename}/verify")
def verify_backup_archive(filename: str) -> dict:
    try:
        return verify_backup(filename)
    except FileNotFoundError as exc:
        raise HTTPException(404, "backup not found") from exc


@router.get("/archive/backups/{filename}/restore-guide")
def backup_restore_guide(filename: str) -> dict:
    try:
        return restore_guide(filename)
    except FileNotFoundError as exc:
        raise HTTPException(404, "backup not found") from exc


@router.get("/archive/backups/{filename}")
def download_backup(filename: str) -> FileResponse:
    try:
        path = resolve_backup(filename)
    except FileNotFoundError as exc:
        raise HTTPException(404, "backup not found") from exc
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.get("/archive/export/json")
def download_json_export(session: Session = Depends(get_session)) -> Response:
    content = json.dumps(export_json(session), ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="papermind-export.json"'},
    )


@router.get("/archive/export/bibtex")
def download_bibtex_export(session: Session = Depends(get_session)) -> Response:
    return Response(
        content=export_bibtex(session),
        media_type="application/x-bibtex; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="papermind-library.bib"'},
    )


@router.get("/archive/export/ris")
def download_ris_export(session: Session = Depends(get_session)) -> Response:
    return Response(
        content=export_ris(session),
        media_type="application/x-research-info-systems; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="papermind-library.ris"'},
    )
