from sqlmodel import Session

from app.ai_ops.concepts import _parse_concepts
from app.db.engine import get_engine
from app.ingestion.service import resolve_and_attach_concepts
from app.models import Paper


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
    pg = client.get("/api/graph/paper").json()
    assert len(pg["nodes"]) == 2
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

    cg_filtered = client.get("/api/graph/concept?min_papers=2").json()
    fnames = {n["name"] for n in cg_filtered["nodes"]}
    assert "shared" in fnames
    assert "unique to p3" not in fnames  # R4: low-frequency concept filtered
