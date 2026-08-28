from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Collection, CollectionPaper, Paper, PaperTag, Tag
from app.models.base import utcnow


def _name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("name is required")
    return name


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _paper(session: Session, paper_id: int) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        raise LookupError("paper not found")
    return paper


def _tag(session: Session, tag_id: int) -> Tag:
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise LookupError("tag not found")
    return tag


def _collection(session: Session, collection_id: int) -> Collection:
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise LookupError("collection not found")
    return collection


def _active_tag_count(session: Session, tag_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(PaperTag)
            .join(Paper, Paper.id == PaperTag.paper_id)
            .where(PaperTag.tag_id == tag_id, Paper.is_deleted == False)  # noqa: E712
        ).one()
    )


def _active_collection_count(session: Session, collection_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(CollectionPaper)
            .join(Paper, Paper.id == CollectionPaper.paper_id)
            .where(
                CollectionPaper.collection_id == collection_id,
                Paper.is_deleted == False,  # noqa: E712
            )
        ).one()
    )


def serialize_tag(session: Session, tag: Tag) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "user_created": tag.user_created,
        "paper_count": _active_tag_count(session, tag.id),
    }


def serialize_collection(session: Session, collection: Collection) -> dict:
    return {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "paper_count": _active_collection_count(session, collection.id),
    }


def list_tags(session: Session) -> list[dict]:
    rows = session.exec(select(Tag).order_by(Tag.name)).all()
    return [serialize_tag(session, row) for row in rows]


def list_collections(session: Session) -> list[dict]:
    rows = session.exec(select(Collection).order_by(Collection.name)).all()
    return [serialize_collection(session, row) for row in rows]


def create_or_update_tag(session: Session, payload: dict) -> tuple[dict, bool]:
    name = _name(payload.get("name"))
    existing = session.exec(select(Tag).where(Tag.name == name)).first()
    created = existing is None
    tag = existing or Tag(name=name)
    if "color" in payload:
        tag.color = _optional_text(payload.get("color"))
    tag.updated_at = utcnow()
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return serialize_tag(session, tag), created


def create_or_update_collection(session: Session, payload: dict) -> tuple[dict, bool]:
    name = _name(payload.get("name"))
    existing = session.exec(select(Collection).where(Collection.name == name)).first()
    created = existing is None
    collection = existing or Collection(name=name)
    if "description" in payload:
        collection.description = _optional_text(payload.get("description"))
    collection.updated_at = utcnow()
    session.add(collection)
    session.commit()
    session.refresh(collection)
    return serialize_collection(session, collection), created


def attach_tag_to_paper(session: Session, paper_id: int, tag_id: int) -> tuple[dict, bool]:
    _paper(session, paper_id)
    tag = _tag(session, tag_id)
    existing = session.get(PaperTag, (paper_id, tag_id))
    created = existing is None
    if created:
        session.add(PaperTag(paper_id=paper_id, tag_id=tag_id))
        session.commit()
    return serialize_tag(session, tag), created


def remove_tag_from_paper(session: Session, paper_id: int, tag_id: int) -> None:
    _paper(session, paper_id)
    _tag(session, tag_id)
    existing = session.get(PaperTag, (paper_id, tag_id))
    if existing is not None:
        session.delete(existing)
        session.commit()


def add_paper_to_collection(session: Session, collection_id: int, paper_id: int) -> tuple[dict, bool]:
    collection = _collection(session, collection_id)
    _paper(session, paper_id)
    existing = session.get(CollectionPaper, (collection_id, paper_id))
    created = existing is None
    if created:
        session.add(CollectionPaper(collection_id=collection_id, paper_id=paper_id))
        session.commit()
    return serialize_collection(session, collection), created


def remove_paper_from_collection(session: Session, collection_id: int, paper_id: int) -> None:
    _collection(session, collection_id)
    _paper(session, paper_id)
    existing = session.get(CollectionPaper, (collection_id, paper_id))
    if existing is not None:
        session.delete(existing)
        session.commit()


def delete_tag(session: Session, tag_id: int) -> None:
    tag = _tag(session, tag_id)
    for link in session.exec(select(PaperTag).where(PaperTag.tag_id == tag_id)).all():
        session.delete(link)
    session.delete(tag)
    session.commit()


def delete_collection(session: Session, collection_id: int) -> None:
    collection = _collection(session, collection_id)
    for link in session.exec(
        select(CollectionPaper).where(CollectionPaper.collection_id == collection_id)
    ).all():
        session.delete(link)
    session.delete(collection)
    session.commit()


def paper_tags(session: Session, paper_id: int) -> list[dict]:
    links = session.exec(select(PaperTag).where(PaperTag.paper_id == paper_id)).all()
    if not links:
        return []
    tag_ids = [link.tag_id for link in links]
    tags = session.exec(select(Tag).where(Tag.id.in_(tag_ids)).order_by(Tag.name)).all()
    return [{"id": tag.id, "name": tag.name, "color": tag.color} for tag in tags]


def paper_collections(session: Session, paper_id: int) -> list[dict]:
    links = session.exec(select(CollectionPaper).where(CollectionPaper.paper_id == paper_id)).all()
    if not links:
        return []
    collection_ids = [link.collection_id for link in links]
    collections = session.exec(
        select(Collection).where(Collection.id.in_(collection_ids)).order_by(Collection.name)
    ).all()
    return [{"id": row.id, "name": row.name} for row in collections]
