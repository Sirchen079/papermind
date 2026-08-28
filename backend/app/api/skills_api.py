import json
from pathlib import Path

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app import paths
from app.api.deps import get_session
from app.models import Concept, Paper, Skill
from app.models.base import utcnow
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
    return {"loaded": count}


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
def run_skill(sid: int, body: RunIn, session: Session = Depends(get_session)) -> dict:
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
