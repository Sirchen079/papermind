from sqlmodel import Session, SQLModel, select

from app.db.engine import get_engine, make_engine
from app.models import Paper


def test_organization_models_roundtrip(tmp_path):
    from app.models import Collection, CollectionPaper, PaperTag, Tag

    eng = make_engine(tmp_path / "organization.sqlite")
    SQLModel.metadata.create_all(eng)

    with Session(eng) as session:
        paper = Paper(source="manual", title="Organization Paper")
        tag = Tag(name="核心方法", color="#2563eb")
        collection = Collection(name="毕业论文必读", description="论文写作阶段反复阅读")
        session.add(paper)
        session.add(tag)
        session.add(collection)
        session.commit()
        session.refresh(paper)
        session.refresh(tag)
        session.refresh(collection)
        paper_id = paper.id

        session.add(PaperTag(paper_id=paper.id, tag_id=tag.id))
        session.add(CollectionPaper(collection_id=collection.id, paper_id=paper.id))
        session.commit()

        tags = session.exec(select(Tag)).all()
        paper_tags = session.exec(select(PaperTag)).all()
        collections = session.exec(select(Collection)).all()
        collection_papers = session.exec(select(CollectionPaper)).all()

    assert [row.name for row in tags] == ["核心方法"]
    assert paper_tags[0].paper_id == paper_id
    assert [row.name for row in collections] == ["毕业论文必读"]
    assert collection_papers[0].paper_id == paper_id


def test_tags_api_assigns_tags_and_papers_list_includes_them(client):
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Tagged Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        paper_id = paper.id

    created = client.post("/api/tags", json={"name": " 核心方法 ", "color": "#2563eb"})
    assert created.status_code == 201
    tag_id = created.json()["id"]
    assert created.json()["name"] == "核心方法"

    duplicate = client.post("/api/tags", json={"name": "核心方法", "color": "#0f766e"})
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == tag_id
    assert duplicate.json()["color"] == "#0f766e"

    attached = client.post(f"/api/papers/{paper_id}/tags/{tag_id}")
    assert attached.status_code == 201
    assert attached.json()["name"] == "核心方法"

    tags = client.get("/api/tags").json()
    assert tags[0]["paper_count"] == 1

    paper_row = next(row for row in client.get("/api/papers").json() if row["id"] == paper_id)
    assert paper_row["tags"] == [{"id": tag_id, "name": "核心方法", "color": "#0f766e"}]

    assert client.delete(f"/api/papers/{paper_id}/tags/{tag_id}").status_code == 204
    paper_row = next(row for row in client.get("/api/papers").json() if row["id"] == paper_id)
    assert paper_row["tags"] == []


def test_collections_api_membership_and_export(client):
    from app.archive.service import export_json

    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Collection Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        paper_id = paper.id

    created = client.post(
        "/api/collections",
        json={"name": "毕业论文必读", "description": "论文写作阶段反复阅读"},
    )
    assert created.status_code == 201
    collection_id = created.json()["id"]

    added = client.post(f"/api/collections/{collection_id}/papers/{paper_id}")
    assert added.status_code == 201
    assert added.json()["paper_count"] == 1

    collections = client.get("/api/collections").json()
    assert collections[0]["paper_count"] == 1

    paper_row = next(row for row in client.get("/api/papers").json() if row["id"] == paper_id)
    assert paper_row["collections"] == [{"id": collection_id, "name": "毕业论文必读"}]

    with Session(get_engine()) as session:
        exported = export_json(session)

    assert exported["tags"] == []
    assert exported["paper_tags"] == []
    assert exported["collections"][0]["name"] == "毕业论文必读"
    assert exported["collection_papers"][0]["paper_id"] == paper_id

    assert client.delete(f"/api/collections/{collection_id}/papers/{paper_id}").status_code == 204
    paper_row = next(row for row in client.get("/api/papers").json() if row["id"] == paper_id)
    assert paper_row["collections"] == []
