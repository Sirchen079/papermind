import json
from pathlib import Path

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app import paths
from app.api.deps import get_session
from app.models import Concept, Paper, Skill
from app.models.base import utcnow
from app.security.local_token import require_local_token
from app.skills.loader import load_skills_from_dir

router = APIRouter()


def default_skills_dir() -> Path:
    # backend/app/api/skills_api.py -> backend/user_skills (dev),
    # or _internal/backend/user_skills inside a PyInstaller bundle.
    return paths.user_skills_dir()


class SkillIn(BaseModel):
    name: str
    description: str | None = None
    type: Literal["instruction", "template", "tool", "persona"] = "instruction"
    trigger: Literal["auto", "keyword", "manual", "pipeline"] = "manual"
    keywords: list[str] = Field(default_factory=list)
    model_role: str | None = None
    body: str | None = None
    enabled: bool = True


def _clean_keywords(values: list[str]) -> list[str]:
    return [k.strip() for k in values if isinstance(k, str) and k.strip()]


def _keywords(s: Skill) -> list[str]:
    try:
        raw = json.loads(s.keywords_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return _clean_keywords(raw)


def _public(s: Skill) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "type": s.type,
        "trigger": s.trigger,
        "keywords": _keywords(s),
        "model_role": s.model_role,
        "body": s.body,
        "enabled": s.enabled,
        "source": s.source,
        "builtin_id": s.file_path.removeprefix('builtin://') if (s.file_path or '').startswith('builtin://') else None,
    }


@router.get("/skills")
def list_skills(session: Session = Depends(get_session)) -> list[dict]:
    return [_public(s) for s in session.exec(select(Skill).order_by(Skill.id)).all()]


@router.post("/skills")
def upsert_skill(body: SkillIn, session: Session = Depends(get_session)) -> dict:
    existing = session.exec(select(Skill).where(Skill.name == body.name)).first()
    s = existing if existing is not None else Skill(name=body.name)
    s.description = body.description
    s.type = body.type
    s.trigger = body.trigger
    s.keywords_json = json.dumps(_clean_keywords(body.keywords), ensure_ascii=False)
    s.model_role = body.model_role
    s.body = body.body
    s.enabled = body.enabled
    s.updated_at = utcnow()
    session.add(s)
    session.commit()
    session.refresh(s)
    return _public(s)


@router.delete("/skills/{sid}", status_code=204)
def delete_skill(sid: int, session: Session = Depends(get_session)) -> None:
    s = session.get(Skill, sid)
    if s is not None:
        session.delete(s)
        session.commit()


@router.post("/skills/reload")
def reload_skills(session: Session = Depends(get_session)) -> dict:
    count = load_skills_from_dir(session, default_skills_dir())
    from app.skills.builtin import sync
    return {"loaded": count, "builtin_loaded": sync(session)}


@router.get('/builtin-skills')
def builtin_catalog():
    from app.skills.builtin import public_catalog
    return public_catalog()


def _imported_family(family: dict) -> dict:
    """ImportedSkillFamily 契约：前端按此消费，字段名保持稳定。"""
    return {
        'id': family['id'],
        'name': family['name'],
        'source': family['source'],
        'revision': family['revision'],
        'license': family.get('license'),
        'license_file': family.get('license_file'),
        'imported_at': family.get('imported_at'),
        'bytes': family.get('bytes', 0),
        'file_count': len(family.get('files') or {}),
        'skills': [{'id': s['id'], 'name': s.get('name') or s['slug'],
                    'description': s.get('description') or '', 'license': s.get('license')}
                   for s in family.get('skills', [])],
    }


class ImportGithubIn(BaseModel):
    url: str


class ImportFolderIn(BaseModel):
    path: str


def _import(family: dict, session: Session) -> dict:
    from app.skills.builtin import sync
    uris = ['builtin://' + s['id'] for s in family.get('skills', [])]
    before = len(session.exec(select(Skill).where(Skill.file_path.in_(uris))).all())
    sync(session)  # First import also registers pending built-in rows.
    after = len(session.exec(select(Skill).where(Skill.file_path.in_(uris))).all())
    return {**_imported_family(family), 'skills_added': after - before}


@router.get('/skill-imports')
def list_skill_imports(_: str = Depends(require_local_token)) -> list[dict]:
    from app.skills import importer
    return [_imported_family(f) for f in importer.catalog()['families']]


@router.post('/skill-imports/github')
def import_skill_github(body: ImportGithubIn, session: Session = Depends(get_session),
                        _: str = Depends(require_local_token)) -> dict:
    from app.skills import importer
    try:
        family = importer.import_github(body.url)
    except importer.DownloadError as exc:
        raise HTTPException(502, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _import(family, session)


@router.post('/skill-imports/folder')
def import_skill_folder(body: ImportFolderIn, session: Session = Depends(get_session),
                        _: str = Depends(require_local_token)) -> dict:
    from app.skills import importer
    try:
        family = importer.import_folder(body.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _import(family, session)


@router.post('/skill-imports/zip')
async def import_skill_zip(file: UploadFile = File(...), session: Session = Depends(get_session),
                           _: str = Depends(require_local_token)) -> dict:
    from app.skills import importer
    raw = await file.read(importer.MAX_BYTES + 1)
    await file.close()
    if len(raw) > importer.MAX_BYTES:
        raise HTTPException(400, 'zip 文件超过 100MB 上限')
    try:
        family = importer.import_zip(raw, file.filename or 'upload.zip')
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _import(family, session)


@router.delete('/skill-imports/{family_id}', status_code=204)
def delete_skill_import(family_id: str, session: Session = Depends(get_session),
                        _: str = Depends(require_local_token)) -> None:
    from app.skills import importer
    try:
        importer.remove(family_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    prefix = 'builtin://' + family_id + '/'
    for skill in session.exec(select(Skill).where(Skill.file_path.startswith(prefix))).all():
        session.delete(skill)
    session.commit()


@router.get('/builtin-skills/resources')
def builtin_resources(skill_id:str):
    from app.skills.builtin import resources
    try:return resources(skill_id)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc


@router.get('/builtin-skills/runs/{run_id}/files/{artifact}')
def download_skill_run(run_id: str, artifact: str):
    from app.skills.paper_card import artifact_path
    from fastapi.responses import FileResponse
    try:
        path = artifact_path(run_id, artifact)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, filename=path.name)


@router.get('/builtin-skills/resource')
def builtin_resource(skill_id:str,path:str='SKILL.md',start:int=0):
    from app.skills.builtin import read_resource
    try:return read_resource(skill_id,path,start)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc


@router.get('/builtin-skills/resource/download')
def download_builtin_resource(skill_id:str,path:str='SKILL.md'):
    from app.skills.builtin import resource_path
    from fastapi.responses import FileResponse
    try:resolved=resource_path(skill_id,path)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    return FileResponse(resolved,filename=resolved.name)


class RunIn(BaseModel):
    input: str = ""


def _run_context(session: Session, user_input: str = "") -> dict:
    """Build the library context handed to a tool skill (JSON via temp file)."""
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    concepts = session.exec(select(Concept)).all()
    return {
        "library": {"papers": len(papers), "concepts": len(concepts)},
        "papers": [
            {
                "id": p.id,
                "title": p.title,
                "year": p.year,
                "abstract": (p.abstract or "")[:500],
            }
            for p in papers[:50]
        ],
        "input": user_input,
    }


@router.post("/skills/{sid}/run")
def run_skill(
    sid: int,
    body: RunIn,
    session: Session = Depends(get_session),
    _: str = Depends(require_local_token),
) -> dict:
    """Execute a tool-type skill in the sandbox and return its output.

    Only ``tool`` skills are runnable; their body is Python executed in an
    isolated subprocess (see app.skills.sandbox). The library context is
    pre-loaded into ``library``/``papers``/``user_input`` globals; anything the
    skill prints becomes ``stdout``.
    """
    s = session.get(Skill, sid)
    if s is None:
        raise HTTPException(404, "skill not found")
    if s.type != "tool":
        raise HTTPException(400, "only tool-type skills are runnable")
    if not (s.body or "").strip():
        raise HTTPException(400, "skill has no code body")

    from app.skills.sandbox import run_tool

    result = run_tool(s.body, _run_context(session, body.input))
    return result.to_dict()
