from app.models.base import utc_iso
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.experiment.service import (
    ExperimentTransitionError,
    add_log,
    create_experiment,
    delete_experiment,
    delete_log,
    get_experiment,
    list_experiments,
    list_logs,
    patch_experiment,
    remove_paper_link,
    upsert_paper_link,
)

router = APIRouter()


class PaperLinkIn(BaseModel):
    model_config = {"extra": "forbid"}

    paper_id: int
    role: str
    note: str | None = None


class ExperimentIn(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    project_id: int
    idea_id: int | None = None
    hypothesis: str | None = None
    status: str | None = None
    papers: list[PaperLinkIn] | None = None


class ExperimentPatchIn(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = None
    hypothesis: str | None = None
    status: str | None = None
    project_id: int | None = None
    idea_id: int | None = None


class LogIn(BaseModel):
    model_config = {"extra": "forbid"}

    content: str


def _run(fn, *args, **kwargs):  # noqa: ANN001
    try:
        return fn(*args, **kwargs)
    except ExperimentTransitionError as exc:
        # 非法状态跳转 → 结构化 400（区别于枚举校验的 422）。
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/experiments")
def api_list_experiments(
    status: str | None = None,
    project_id: int | None = None,
    idea_id: int | None = None,
    include_hidden: bool = False,
    session: Session = Depends(get_session),
) -> list[dict]:
    return _run(
        list_experiments,
        session,
        status=status,
        project_id=project_id,
        idea_id=idea_id,
        include_hidden=include_hidden,
    )


@router.post("/experiments", status_code=201)
def api_create_experiment(body: ExperimentIn, session: Session = Depends(get_session)) -> dict:
    experiment = _run(
        create_experiment,
        session,
        name=body.name,
        project_id=body.project_id,
        idea_id=body.idea_id,
        hypothesis=body.hypothesis,
        status=body.status,
        paper_links=[link.model_dump() for link in (body.papers or [])],
    )
    return get_experiment(session, experiment.id)


@router.get("/experiments/{experiment_id}")
def api_get_experiment(experiment_id: int, session: Session = Depends(get_session)) -> dict:
    return _run(get_experiment, session, experiment_id)


@router.patch("/experiments/{experiment_id}")
def api_patch_experiment(
    experiment_id: int, body: ExperimentPatchIn, session: Session = Depends(get_session)
) -> dict:
    fields = body.model_dump(exclude_unset=True)
    _run(patch_experiment, session, experiment_id, fields)
    return get_experiment(session, experiment_id)


@router.delete("/experiments/{experiment_id}", status_code=204)
def api_delete_experiment(experiment_id: int, session: Session = Depends(get_session)) -> None:
    _run(delete_experiment, session, experiment_id)


@router.post("/experiments/{experiment_id}/logs", status_code=201)
def api_add_log(experiment_id: int, body: LogIn, session: Session = Depends(get_session)) -> dict:
    log = _run(add_log, session, experiment_id, body.content)
    return {
        "id": log.id,
        "experiment_id": log.experiment_id,
        "content": log.content,
        "created_at": utc_iso(log.created_at),
    }


@router.get("/experiments/{experiment_id}/logs")
def api_list_logs(experiment_id: int, session: Session = Depends(get_session)) -> list[dict]:
    return _run(list_logs, session, experiment_id)


@router.delete("/experiments/{experiment_id}/logs/{log_id}", status_code=204)
def api_delete_log(
    experiment_id: int, log_id: int, session: Session = Depends(get_session)
) -> None:
    _run(delete_log, session, experiment_id, log_id)


@router.post("/experiments/{experiment_id}/papers", status_code=201)
def api_link_paper(
    experiment_id: int, body: PaperLinkIn, session: Session = Depends(get_session)
) -> dict:
    link = _run(upsert_paper_link, session, experiment_id, body.paper_id, body.role, body.note)
    return {
        "experiment_id": link.experiment_id,
        "paper_id": link.paper_id,
        "role": link.role,
        "note": link.note,
    }


@router.delete("/experiments/{experiment_id}/papers/{paper_id}/{role}", status_code=204)
def api_unlink_paper(
    experiment_id: int, paper_id: int, role: str, session: Session = Depends(get_session)
) -> None:
    _run(remove_paper_link, session, experiment_id, paper_id, role)
