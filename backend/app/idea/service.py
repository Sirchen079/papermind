"""Idea entity business logic: lifecycle, paper links (P9.1)."""

from sqlmodel import Session, select

from app.models import Idea, IdeaPaperLink, Paper, Project
from app.models.base import utcnow
from app.models.idea import (
    IDEA_ORIGINS,
    IDEA_PAPER_ROLES,
    IDEA_PRIORITIES,
    IDEA_STATUSES,
    IDEA_TRANSITIONS,
)


class IdeaTransitionError(ValueError):
    """Raised on an illegal status transition; message names allowed targets."""


def _idea(session: Session, idea_id: int) -> Idea:
    idea = session.get(Idea, idea_id)
    if idea is None or idea.is_deleted:
        raise LookupError("idea not found")
    return idea


def _validate_choice(value: str | None, allowed: tuple[str, ...], field: str, default: str) -> str:
    if value is None:
        return default
    if value not in allowed:
        raise ValueError(f"{field} must be one of {list(allowed)}")
    return value


def list_ideas(
    session: Session,
    status: str | None = None,
    priority: str | None = None,
    project_id: int | None = None,
) -> list[dict]:
    """Non-deleted ideas newest first, each with its paper links."""
    conditions = [Idea.is_deleted == False]  # noqa: E712
    if status is not None:
        conditions.append(Idea.status == status)
    if priority is not None:
        conditions.append(Idea.priority == priority)
    if project_id is not None:
        conditions.append(Idea.project_id == project_id)
    ideas = session.exec(
        select(Idea).where(*conditions).order_by(Idea.id.desc())
    ).all()
    return [_idea_public(session, idea) for idea in ideas]


def _idea_public(session: Session, idea: Idea) -> dict:
    links = session.exec(
        select(IdeaPaperLink).where(IdeaPaperLink.idea_id == idea.id).order_by(IdeaPaperLink.id)
    ).all()
    paper_ids = [link.paper_id for link in links]
    titles = {
        p.id: p.title
        for p in session.exec(select(Paper).where(Paper.id.in_(paper_ids))).all()
    } if paper_ids else {}
    return {
        "id": idea.id,
        "title": idea.title,
        "content": idea.content,
        "hypothesis": idea.hypothesis,
        "status": idea.status,
        "priority": idea.priority,
        "origin": idea.origin,
        "project_id": idea.project_id,
        "created_at": idea.created_at.isoformat(),
        "updated_at": idea.updated_at.isoformat(),
        "closed_at": idea.closed_at.isoformat() if idea.closed_at else None,
        "papers": [
            {
                "paper_id": link.paper_id,
                "title": titles.get(link.paper_id),
                "role": link.role,
                "note": link.note,
            }
            for link in links
        ],
    }


def create_idea(
    session: Session,
    title: str,
    content: str = "",
    hypothesis: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    origin: str | None = None,
    project_id: int | None = None,
    paper_links: list[dict] | None = None,
) -> Idea:
    title = str(title or "").strip()
    if not title:
        raise ValueError("title is required")
    status = _validate_choice(status, IDEA_STATUSES, "status", "proposed")
    priority = _validate_choice(priority, IDEA_PRIORITIES, "priority", "normal")
    origin = _validate_choice(origin, IDEA_ORIGINS, "origin", "manual")
    if project_id is not None and session.get(Project, project_id) is None:
        raise LookupError("project not found")

    idea = Idea(
        title=title,
        content=str(content or ""),
        hypothesis=(str(hypothesis).strip() or None) if hypothesis else None,
        status=status,
        priority=priority,
        origin=origin,
        project_id=project_id,
    )
    # Validate every association before creating anything, then commit the
    # idea and its links together. Retrying a failed create leaves no residue.
    links = set()
    for link in paper_links or []:
        pid, role = link.get("paper_id"), link.get("role")
        if role not in IDEA_PAPER_ROLES:
            raise ValueError(f"role must be one of {list(IDEA_PAPER_ROLES)}")
        paper = session.get(Paper, pid) if pid is not None else None
        if paper is None or paper.is_deleted:
            raise LookupError("paper not found")
        links.add((pid, role))
    try:
        session.add(idea)
        session.flush()
        for pid, role in links:
            session.add(IdeaPaperLink(idea_id=idea.id, paper_id=pid, role=role))
        session.commit()
        session.refresh(idea)
    except Exception:
        session.rollback()
        raise
    return idea


def get_idea(session: Session, idea_id: int) -> dict:
    return _idea_public(session, _idea(session, idea_id))


def patch_idea(session: Session, idea_id: int, fields: dict) -> Idea:
    """Editable fields + state-machine-guarded status transitions."""
    idea = _idea(session, idea_id)

    if "status" in fields and fields["status"] is not None and fields["status"] != idea.status:
        target = _validate_choice(fields["status"], IDEA_STATUSES, "status", idea.status)
        if (idea.status, target) not in IDEA_TRANSITIONS:
            allowed = sorted(t for s, t in IDEA_TRANSITIONS if s == idea.status)
            raise IdeaTransitionError(
                f"cannot move idea from '{idea.status}' to '{target}'; allowed: {allowed}"
            )
        idea.status = target
        if target in ("adopted", "dropped"):
            idea.closed_at = utcnow()

    if "title" in fields and fields["title"] is not None:
        title = str(fields["title"]).strip()
        if not title:
            raise ValueError("title is required")
        idea.title = title
    if "content" in fields and fields["content"] is not None:
        idea.content = str(fields["content"])
    if "hypothesis" in fields:
        hypothesis = fields["hypothesis"]
        idea.hypothesis = (str(hypothesis).strip() or None) if hypothesis else None
    if "priority" in fields and fields["priority"] is not None:
        idea.priority = _validate_choice(fields["priority"], IDEA_PRIORITIES, "priority", idea.priority)
    if "project_id" in fields:
        project_id = fields["project_id"]
        if project_id is not None and session.get(Project, project_id) is None:
            raise LookupError("project not found")
        idea.project_id = project_id

    idea.updated_at = utcnow()
    session.add(idea)
    session.commit()
    session.refresh(idea)
    return idea


def delete_idea(session: Session, idea_id: int) -> None:
    idea = _idea(session, idea_id)
    idea.is_deleted = True
    idea.updated_at = utcnow()
    session.add(idea)
    session.commit()


def upsert_paper_link(session: Session, idea_id: int, paper_id: int, role: str, note: str | None = None) -> IdeaPaperLink:
    """Attach a paper to an idea in a role; idempotent per (idea, paper, role)."""
    idea = _idea(session, idea_id)
    if role not in IDEA_PAPER_ROLES:
        raise ValueError(f"role must be one of {list(IDEA_PAPER_ROLES)}")
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        raise LookupError("paper not found")

    existing = session.exec(
        select(IdeaPaperLink).where(
            IdeaPaperLink.idea_id == idea.id,
            IdeaPaperLink.paper_id == paper_id,
            IdeaPaperLink.role == role,
        )
    ).first()
    if existing is not None:
        if note is not None and note != existing.note:
            existing.note = note
            session.add(existing)
            session.commit()
        return existing

    link = IdeaPaperLink(idea_id=idea.id, paper_id=paper_id, role=role, note=note)
    session.add(link)
    idea.updated_at = utcnow()
    session.add(idea)
    session.commit()
    session.refresh(link)
    return link


def remove_paper_link(session: Session, idea_id: int, paper_id: int, role: str) -> None:
    _idea(session, idea_id)
    link = session.exec(
        select(IdeaPaperLink).where(
            IdeaPaperLink.idea_id == idea_id,
            IdeaPaperLink.paper_id == paper_id,
            IdeaPaperLink.role == role,
        )
    ).first()
    if link is None:
        raise LookupError("paper link not found")
    session.delete(link)
    session.commit()
