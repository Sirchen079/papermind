"""Skill activation rules — which skills are active in a given context.

Skills declare a ``trigger`` (auto | keyword | manual | pipeline). For a chat
turn, the rules are:

  - auto:      always active.
  - keyword:   active only when one of its keywords appears in the user message.
  - manual:    user-invoked (e.g. a future explicit command) — never auto-injected.
  - pipeline:  runs during ingestion, not chat.

Only ``instruction`` and ``persona`` skills carry a prompt body worth injecting.
"""
import json
import re

from sqlmodel import Session, select

from app.models import Skill


def _keywords(skill: Skill) -> list[str]:
    try:
        raw = json.loads(skill.keywords_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [k.strip() for k in raw if isinstance(k, str) and k.strip()]


def _matches_keyword(message: str, keyword: str) -> bool:
    """Match ASCII word keywords by token boundary; phrases/non-ASCII by contains."""
    msg = (message or "").lower()
    kw = keyword.lower().strip()
    if not kw:
        return False
    if re.fullmatch(r"[a-z0-9_]+", kw):
        return re.search(rf"(?<![a-z0-9_]){re.escape(kw)}(?![a-z0-9_])", msg) is not None
    return kw in msg


def select_for_chat(session: Session, user_message: str) -> list[Skill]:
    """Return the instruction/persona skills active for this chat turn."""
    out: list[Skill] = []
    for s in session.exec(select(Skill).where(Skill.enabled == True).order_by(Skill.id)).all():  # noqa: E712
        if s.type not in ("instruction", "persona") or not s.body:
            continue
        if s.trigger == "auto":
            out.append(s)
        elif s.trigger == "keyword" and any(_matches_keyword(user_message, kw) for kw in _keywords(s)):
            out.append(s)
        # manual / pipeline are not auto-injected into chat
    return out
