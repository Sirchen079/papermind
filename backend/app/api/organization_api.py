from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.organization import service

router = APIRouter()


class TagIn(BaseModel):
    name: str
    color: str | None = None


class CollectionIn(BaseModel):
    name: str
    description: str | None = None


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    return HTTPException(500, "organization error")


@router.get("/tags")
def list_tags(session: Session = Depends(get_session)) -> list[dict]:
    return service.list_tags(session)


@router.post("/tags")
def create_tag(body: TagIn, response: Response, session: Session = Depends(get_session)) -> dict:
    try:
        tag, created = service.create_or_update_tag(session, body.model_dump())
    except (LookupError, ValueError) as exc:
        raise _map_error(exc) from exc
    response.status_code = 201 if created else 200
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, session: Session = Depends(get_session)) -> None:
    try:
        service.delete_tag(session, tag_id)
    except (LookupError, ValueError) as exc:
        raise _map_error(exc) from exc


@router.post("/papers/{paper_id}/tags/{tag_id}")
def attach_tag(
    paper_id: int,
    tag_id: int,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    try:
        tag, created = service.attach_tag_to_paper(session, paper_id, tag_id)
    except (LookupError, ValueError) as exc:
        raise _map_error(exc) from exc
    response.status_code = 201 if created else 200
    return tag


@router.delete("/papers/{paper_id}/tags/{tag_id}", status_code=204)
def remove_tag(paper_id: int, tag_id: int, session: Session = Depends(get_session)) -> None:
    try:
        service.remove_tag_from_paper(session, paper_id, tag_id)
    except (LookupError, ValueError) as exc:
        raise _map_error(exc) from exc


@router.get("/collections")
def list_collections(session: Session = Depends(get_session)) -> list[dict]:
    return service.list_collections(session)


@router.post("/collections")
def create_collection(
    body: CollectionIn,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    try:
        collection, created = service.create_or_update_collection(session, body.model_dump())
    except (LookupError, ValueError) as exc:
        raise _map_error(exc) from exc
    response.status_code = 201 if created else 200
    return collection


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: int, session: Session = Depends(get_session)) -> None:
    try:
        service.delete_collection(session, collection_id)
    except (LookupError, ValueError) as exc:
        raise _map_error(exc) from exc


@router.post("/collections/{collection_id}/papers/{paper_id}")
def add_paper_to_collection(
    collection_id: int,
    paper_id: int,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    try:
        collection, created = service.add_paper_to_collection(session, collection_id, paper_id)
    except (LookupError, ValueError) as exc:
        raise _map_error(exc) from exc
    response.status_code = 201 if created else 200
    return collection


@router.delete("/collections/{collection_id}/papers/{paper_id}", status_code=204)
def remove_paper_from_collection(
    collection_id: int,
    paper_id: int,
    session: Session = Depends(get_session),
) -> None:
    try:
        service.remove_paper_from_collection(session, collection_id, paper_id)
    except (LookupError, ValueError) as exc:
        raise _map_error(exc) from exc
