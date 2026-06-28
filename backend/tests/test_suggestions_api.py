from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Concept, Paper, PaperConcept


def _seed_connected_library():
    """Three papers: A & B share a concept; all three share a hub concept."""
    with Session(get_engine()) as s:
        a = Paper(source="bibtex", title="Alpha")
        b = Paper(source="bibtex", title="Beta")
        g = Paper(source="bibtex", title="Gamma")
        s.add_all([a, b, g])
        s.commit()
        for p in (a, b, g):
            s.refresh(p)
        shared = Concept(name="transformers", normalized_key="transformers")
        hub = Concept(name="DeepLearning", normalized_key="deeplearning")
        s.add_all([shared, hub])
        s.commit()
        for c in (shared, hub):
            s.refresh(c)
        s.add_all(
            [
                PaperConcept(paper_id=a.id, concept_id=shared.id),
                PaperConcept(paper_id=b.id, concept_id=shared.id),
                PaperConcept(paper_id=a.id, concept_id=hub.id),
                PaperConcept(paper_id=b.id, concept_id=hub.id),
                PaperConcept(paper_id=g.id, concept_id=hub.id),
            ]
        )
        s.commit()
        return a.id, b.id


def test_generate_then_list(client):
    _seed_connected_library()
    res = client.post("/api/suggestions/generate")
    assert res.status_code == 200
    assert res.json()["created"] >= 1

    listed = client.get("/api/suggestions").json()
    kinds = {s["kind"] for s in listed}
    assert "concept_link" in kinds
    # titles are resolved for linked papers
    link = next(s for s in listed if s["kind"] == "concept_link")
    assert link["related_paper"] is not None
    assert link["detail"]["count"] >= 1


def test_generate_is_idempotent(client):
    _seed_connected_library()
    first = client.post("/api/suggestions/generate").json()["created"]
    second = client.post("/api/suggestions/generate").json()["created"]
    assert first >= 1
    assert second == 0  # rescan finds nothing new


def test_status_filter_and_patch(client):
    _seed_connected_library()
    client.post("/api/suggestions/generate")
    only_new = client.get("/api/suggestions?status=new").json()
    assert len(only_new) >= 1
    assert all(s["status"] == "new" for s in only_new)

    sid = only_new[0]["id"]
    patched = client.patch(f"/api/suggestions/{sid}", json={"status": "dismissed"}).json()
    assert patched["status"] == "dismissed"
    # dismissed ones no longer appear under status=new
    assert sid not in [s["id"] for s in client.get("/api/suggestions?status=new").json()]
    assert sid in [s["id"] for s in client.get("/api/suggestions?status=dismissed").json()]


def test_patch_rejects_bad_status(client):
    _seed_connected_library()
    client.post("/api/suggestions/generate")
    sid = client.get("/api/suggestions").json()[0]["id"]
    res = client.patch(f"/api/suggestions/{sid}", json={"status": "bogus"})
    assert res.status_code == 400


def test_patch_404(client):
    assert client.patch("/api/suggestions/9999", json={"status": "seen"}).status_code == 404
