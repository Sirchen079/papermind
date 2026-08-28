from sqlmodel import Session

from app.ai_ops.concepts import _parse_concepts
from app.db.engine import get_engine
from app.ingestion.service import resolve_and_attach_concepts
from app.models import Concept, Paper, PaperConcept


def test_parse_concepts_array():
    out = _parse_concepts('[{"name":"Transformer","type":"method","evidence":"self-attention"}]')
    assert len(out) == 1
    assert out[0]["name"] == "Transformer"
    assert out[0]["type"] == "method"
    assert _parse_concepts("garbage") == []
    assert _parse_concepts("```json\n[{\"name\":\"CNN\"}]\n```")[0]["name"] == "CNN"


def _make_paper(session, title):
    p = Paper(source="manual", title=title)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def test_concept_resolution_merges_synonyms(client):
    with Session(get_engine()) as s:
        p1 = _make_paper(s, "Paper A")
        p2 = _make_paper(s, "Paper B")
        resolve_and_attach_concepts(s, p1, None, [{"name": "Transformers", "type": "method"}])
        resolve_and_attach_concepts(s, p2, None, [{"name": "transformers!", "type": "method"}])

    cg = client.get("/api/graph/concept").json()
    assert len(cg["nodes"]) == 1  # synonyms merged into one concept
    assert cg["nodes"][0]["count"] == 2
    pg = client.get("/api/graph/paper").json()
    assert len(pg["nodes"]) == 2
    assert {n["count"] for n in pg["nodes"]} == {1}
    assert len(pg["edges"]) == 1  # A and B share the concept
    assert pg["edges"][0]["weight"] == 1


def test_concept_graph_min_papers_filter(client):
    with Session(get_engine()) as s:
        p1 = _make_paper(s, "P1")
        p2 = _make_paper(s, "P2")
        p3 = _make_paper(s, "P3")
        resolve_and_attach_concepts(s, p1, None, [{"name": "shared", "type": "domain"}])
        resolve_and_attach_concepts(s, p2, None, [{"name": "shared", "type": "domain"}])
        resolve_and_attach_concepts(s, p3, None, [{"name": "unique to p3", "type": "domain"}])

    cg_all = client.get("/api/graph/concept?min_papers=1").json()
    names = {n["name"] for n in cg_all["nodes"]}
    assert "shared" in names and "unique to p3" in names
    counts = {n["name"]: n["count"] for n in cg_all["nodes"]}
    assert counts["shared"] == 2
    assert counts["unique to p3"] == 1

    cg_filtered = client.get("/api/graph/concept?min_papers=2").json()
    fnames = {n["name"] for n in cg_filtered["nodes"]}
    assert "shared" in fnames
    assert "unique to p3" not in fnames  # R4: low-frequency concept filtered
    assert {n["name"]: n["count"] for n in cg_filtered["nodes"]}["shared"] == 2


def test_concept_graph_includes_parent_child_hierarchy_edges(client):
    with Session(get_engine()) as s:
        parent_paper = _make_paper(s, "Hierarchy Parent Paper")
        child_paper = _make_paper(s, "Hierarchy Child Paper")
        parent = Concept(name="Representation Learning", normalized_key="representation learning", type="domain")
        child = Concept(
            name="Contrastive Learning",
            normalized_key="contrastive learning",
            type="method",
        )
        s.add(parent)
        s.add(child)
        s.commit()
        s.refresh(parent)
        s.refresh(child)
        child.parent_concept_id = parent.id
        s.add(child)
        s.add(PaperConcept(paper_id=parent_paper.id, concept_id=parent.id))
        s.add(PaperConcept(paper_id=child_paper.id, concept_id=child.id))
        s.commit()
        parent_id = parent.id
        child_id = child.id

    graph = client.get("/api/graph/concept?min_papers=1").json()
    hierarchy_edges = [edge for edge in graph["edges"] if edge.get("edge_type") == "hierarchy"]
    assert hierarchy_edges == [{"source": parent_id, "target": child_id, "weight": 1, "edge_type": "hierarchy"}]

    filtered = client.get("/api/graph/concept?min_papers=2").json()
    assert all(edge.get("edge_type") != "hierarchy" for edge in filtered["edges"])


def test_paper_graph_ignores_stale_links_to_deleted_papers(client):
    with Session(get_engine()) as s:
        active = _make_paper(s, "Active Paper")
        deleted = _make_paper(s, "Deleted Paper")
        deleted.is_deleted = True
        concept = Concept(name="Stale Concept", normalized_key="stale concept", type="method")
        s.add(concept)
        s.commit()
        s.refresh(concept)
        s.add(PaperConcept(paper_id=active.id, concept_id=concept.id))
        s.add(PaperConcept(paper_id=deleted.id, concept_id=concept.id))
        s.commit()
        active_id = active.id
        deleted_id = deleted.id

    graph = client.get("/api/graph/paper").json()

    assert {node["id"] for node in graph["nodes"]} == {active_id}
    assert all(deleted_id not in {edge["source"], edge["target"]} for edge in graph["edges"])
    assert graph["edges"] == []


def test_concept_graph_ignores_stale_links_to_deleted_papers(client):
    with Session(get_engine()) as s:
        active = _make_paper(s, "Active Concept Paper")
        deleted = _make_paper(s, "Deleted Concept Paper")
        deleted.is_deleted = True
        shared = Concept(name="Shared But Active Once", normalized_key="shared active once", type="method")
        active_only = Concept(name="Active Only", normalized_key="active only", type="dataset")
        deleted_only = Concept(name="Deleted Only", normalized_key="deleted only", type="problem")
        s.add(shared)
        s.add(active_only)
        s.add(deleted_only)
        s.commit()
        s.refresh(shared)
        s.refresh(active_only)
        s.refresh(deleted_only)
        s.add(PaperConcept(paper_id=active.id, concept_id=shared.id))
        s.add(PaperConcept(paper_id=active.id, concept_id=active_only.id))
        s.add(PaperConcept(paper_id=deleted.id, concept_id=shared.id))
        s.add(PaperConcept(paper_id=deleted.id, concept_id=deleted_only.id))
        s.commit()

    graph = client.get("/api/graph/concept?min_papers=1").json()
    counts = {node["name"]: node["count"] for node in graph["nodes"]}

    assert counts == {"Shared But Active Once": 1, "Active Only": 1}
    assert graph["edges"] == [
        {
            "source": next(node["id"] for node in graph["nodes"] if node["name"] == "Shared But Active Once"),
            "target": next(node["id"] for node in graph["nodes"] if node["name"] == "Active Only"),
            "weight": 1,
            "edge_type": "cooccurrence",
        }
    ]

    filtered = client.get("/api/graph/concept?min_papers=2").json()
    assert filtered["nodes"] == []
    assert filtered["edges"] == []
