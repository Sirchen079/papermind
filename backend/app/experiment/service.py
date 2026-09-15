"""Experiment entity business logic: lifecycle, paper links, append-only logs (P13)."""

from sqlmodel import Session, select

from app.models import (
    Experiment,
    ExperimentLog,
    ExperimentPaperLink,
    Idea,
    Paper,
    Project,
)
from app.models.base import utcnow, utc_iso
from app.models.experiment import (
    EXPERIMENT_PAPER_ROLES,
    EXPERIMENT_STATUSES,
    EXPERIMENT_TRANSITIONS,
)


class ExperimentTransitionError(ValueError):
    """Raised on an illegal status transition; message names allowed targets."""


def _experiment(session: Session, experiment_id: int) -> Experiment:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None or experiment.is_deleted:
        raise LookupError("experiment not found")
    return experiment


def _validate_choice(value: str | None, allowed: tuple[str, ...], field: str, default: str) -> str:
    if value is None:
        return default
    if value not in allowed:
        raise ValueError(f"{field} must be one of {list(allowed)}")
    return value


def _idea_is_hidden(session: Session, idea_id: int | None) -> bool:
    """An experiment is hidden from default views once its idea is soft-deleted."""
    if idea_id is None:
        return False
    idea = session.get(Idea, idea_id)
    return idea is None or idea.is_deleted


def _experiment_public(session: Session, experiment: Experiment, *, include_hidden: bool = False) -> dict | None:
    if not include_hidden and _idea_is_hidden(session, experiment.idea_id):
        return None
    links = session.exec(
        select(ExperimentPaperLink)
        .where(ExperimentPaperLink.experiment_id == experiment.id)
        .order_by(ExperimentPaperLink.id)
    ).all()
    paper_ids = [link.paper_id for link in links]
    titles = {
        p.id: p.title
        for p in session.exec(select(Paper).where(Paper.id.in_(paper_ids))).all()
    } if paper_ids else {}
    log_count = len(
        session.exec(select(ExperimentLog).where(ExperimentLog.experiment_id == experiment.id)).all()
    )
    return {
        "id": experiment.id,
        "project_id": experiment.project_id,
        "idea_id": experiment.idea_id,
        "name": experiment.name,
        "hypothesis": experiment.hypothesis,
        "status": experiment.status,
        "started_at": utc_iso(experiment.started_at) if experiment.started_at else None,
        "finished_at": utc_iso(experiment.finished_at) if experiment.finished_at else None,
        "created_at": utc_iso(experiment.created_at),
        "updated_at": utc_iso(experiment.updated_at),
        "log_count": log_count,
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


def list_experiments(
    session: Session,
    status: str | None = None,
    project_id: int | None = None,
    idea_id: int | None = None,
    include_hidden: bool = False,
) -> list[dict]:
    """Non-deleted experiments newest first, each with its paper links.

    Experiments whose idea was soft-deleted are retained but hidden from the
    default view (``include_hidden=True`` brings them back); archive export
    always includes them.
    """
    conditions = [Experiment.is_deleted == False]  # noqa: E712
    if status is not None:
        if status not in EXPERIMENT_STATUSES:
            raise ValueError(f"status must be one of {list(EXPERIMENT_STATUSES)}")
        conditions.append(Experiment.status == status)
    if project_id is not None:
        conditions.append(Experiment.project_id == project_id)
    if idea_id is not None:
        conditions.append(Experiment.idea_id == idea_id)
    rows = session.exec(select(Experiment).where(*conditions).order_by(Experiment.id.desc())).all()
    out = []
    for row in rows:
        data = _experiment_public(session, row, include_hidden=include_hidden)
        if data is not None:
            out.append(data)
    return out


def create_experiment(
    session: Session,
    name: str,
    project_id: int,
    idea_id: int | None = None,
    hypothesis: str | None = None,
    status: str | None = None,
    paper_links: list[dict] | None = None,
) -> Experiment:
    name = str(name or "").strip()
    if not name:
        raise ValueError("name is required")
    if session.get(Project, project_id) is None:
        raise LookupError("project not found")
    if idea_id is not None:
        idea = session.get(Idea, idea_id)
        if idea is None or idea.is_deleted:
            raise LookupError("idea not found")
    status = _validate_choice(status, EXPERIMENT_STATUSES, "status", "planned")

    experiment = Experiment(
        name=name,
        project_id=project_id,
        idea_id=idea_id,
        hypothesis=(str(hypothesis).strip() or None) if hypothesis else None,
        status=status,
    )
    session.add(experiment)
    session.commit()
    session.refresh(experiment)

    for link in paper_links or []:
        upsert_paper_link(session, experiment.id, link.get("paper_id"), link.get("role"))
    return experiment


def get_experiment(session: Session, experiment_id: int) -> dict:
    """Single-experiment fetch (works even when the parent idea is hidden)."""
    return _experiment_public(session, _experiment(session, experiment_id), include_hidden=True)


def patch_experiment(session: Session, experiment_id: int, fields: dict) -> Experiment:
    """Editable fields + state-machine-guarded status transitions."""
    experiment = _experiment(session, experiment_id)

    if "status" in fields and fields["status"] is not None and fields["status"] != experiment.status:
        target = _validate_choice(fields["status"], EXPERIMENT_STATUSES, "status", experiment.status)
        if (experiment.status, target) not in EXPERIMENT_TRANSITIONS:
            allowed = sorted(t for s, t in EXPERIMENT_TRANSITIONS if s == experiment.status)
            raise ExperimentTransitionError(
                f"cannot move experiment from '{experiment.status}' to '{target}'; allowed: {allowed}"
            )
        experiment.status = target
        now = utcnow()
        if target == "running" and experiment.started_at is None:
            experiment.started_at = now
        if target in ("done", "abandoned") and experiment.finished_at is None:
            experiment.finished_at = now

    if "name" in fields and fields["name"] is not None:
        name = str(fields["name"]).strip()
        if not name:
            raise ValueError("name is required")
        experiment.name = name
    if "hypothesis" in fields:
        hypothesis = fields["hypothesis"]
        experiment.hypothesis = (str(hypothesis).strip() or None) if hypothesis else None
    if "idea_id" in fields:
        idea_id = fields["idea_id"]
        if idea_id is not None:
            idea = session.get(Idea, idea_id)
            if idea is None or idea.is_deleted:
                raise LookupError("idea not found")
        experiment.idea_id = idea_id
    if "project_id" in fields and fields["project_id"] is not None:
        if session.get(Project, fields["project_id"]) is None:
            raise LookupError("project not found")
        experiment.project_id = fields["project_id"]

    experiment.updated_at = utcnow()
    session.add(experiment)
    session.commit()
    session.refresh(experiment)
    return experiment


def delete_experiment(session: Session, experiment_id: int) -> None:
    """Soft delete — the rows stay (logs/links included), views hide it."""
    experiment = _experiment(session, experiment_id)
    experiment.is_deleted = True
    experiment.updated_at = utcnow()
    session.add(experiment)
    session.commit()


def add_log(session: Session, experiment_id: int, content: str) -> ExperimentLog:
    """Append one timeline entry. Logs are never editable (no patch path)."""
    experiment = _experiment(session, experiment_id)
    content = str(content or "").strip()
    if not content:
        raise ValueError("log content is required")
    row = ExperimentLog(experiment_id=experiment.id, content=content)
    session.add(row)
    experiment.updated_at = utcnow()
    session.add(experiment)
    session.commit()
    session.refresh(row)
    return row


def list_logs(session: Session, experiment_id: int) -> list[dict]:
    """Timeline in chronological order (oldest first)."""
    _experiment(session, experiment_id)
    rows = session.exec(
        select(ExperimentLog)
        .where(ExperimentLog.experiment_id == experiment_id)
        .order_by(ExperimentLog.created_at, ExperimentLog.id)
    ).all()
    return [
        {
            "id": row.id,
            "experiment_id": row.experiment_id,
            "content": row.content,
            "created_at": utc_iso(row.created_at),
        }
        for row in rows
    ]


def delete_log(session: Session, experiment_id: int, log_id: int) -> None:
    """Hard-delete a single log entry (deletion allowed, editing never)."""
    _experiment(session, experiment_id)
    row = session.get(ExperimentLog, log_id)
    if row is None or row.experiment_id != experiment_id:
        raise LookupError("log not found")
    session.delete(row)
    session.commit()


def upsert_paper_link(
    session: Session, experiment_id: int, paper_id: int, role: str, note: str | None = None
) -> ExperimentPaperLink:
    """Attach a paper in a role; idempotent per (experiment, paper, role)."""
    _experiment(session, experiment_id)
    if role not in EXPERIMENT_PAPER_ROLES:
        raise ValueError(f"role must be one of {list(EXPERIMENT_PAPER_ROLES)}")
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        raise LookupError("paper not found")

    existing = session.exec(
        select(ExperimentPaperLink).where(
            ExperimentPaperLink.experiment_id == experiment_id,
            ExperimentPaperLink.paper_id == paper_id,
            ExperimentPaperLink.role == role,
        )
    ).first()
    if existing is not None:
        if note is not None and note != existing.note:
            existing.note = note
            session.add(existing)
            session.commit()
        return existing

    link = ExperimentPaperLink(experiment_id=experiment_id, paper_id=paper_id, role=role, note=note)
    session.add(link)
    experiment = session.get(Experiment, experiment_id)
    experiment.updated_at = utcnow()
    session.add(experiment)
    session.commit()
    session.refresh(link)
    return link


def remove_paper_link(session: Session, experiment_id: int, paper_id: int, role: str) -> None:
    _experiment(session, experiment_id)
    link = session.exec(
        select(ExperimentPaperLink).where(
            ExperimentPaperLink.experiment_id == experiment_id,
            ExperimentPaperLink.paper_id == paper_id,
            ExperimentPaperLink.role == role,
        )
    ).first()
    if link is None:
        raise LookupError("paper link not found")
    session.delete(link)
    session.commit()
