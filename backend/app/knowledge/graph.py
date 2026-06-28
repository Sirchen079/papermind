"""Knowledge-graph construction (paper graph + concept graph).

Edges are derived on query from PaperConcept co-occurrence (the source of
truth). For a local single-user library this is fast enough; materialized
incremental edges (spec F6/G7) are a future optimization for very large libs.
"""
from sqlalchemy import text
from sqlmodel import Session, select

from app.models import Concept, Paper

_PAPER_EDGES_SQL = """
SELECT a.paper_id AS s, b.paper_id AS t, COUNT(*) AS w
FROM paperconcept a
JOIN paperconcept b ON a.concept_id = b.concept_id AND a.paper_id < b.paper_id
GROUP BY a.paper_id, b.paper_id
"""

_CONCEPT_EDGES_SQL = """
SELECT a.concept_id AS s, b.concept_id AS t, COUNT(DISTINCT a.paper_id) AS w
FROM paperconcept a
JOIN paperconcept b ON a.paper_id = b.paper_id AND a.concept_id < b.concept_id
GROUP BY a.concept_id, b.concept_id
"""


def paper_graph(session: Session) -> dict:
    """Nodes = papers; edges = pairs sharing >=1 concept (weight = shared count)."""
    nodes = [
        {"id": p.id, "title": p.title, "year": p.year}
        for p in session.exec(select(Paper).where(Paper.is_deleted == False))  # noqa: E712
    ]
    rows = session.execute(text(_PAPER_EDGES_SQL)).all()
    edges = [{"source": r[0], "target": r[1], "weight": int(r[2])} for r in rows]
    return {"nodes": nodes, "edges": edges}


def concept_graph(session: Session, min_papers: int = 1) -> dict:
    """Nodes = concepts appearing in >=min_papers papers; edges = co-occurrence.

    min_papers filters low-frequency concepts so the graph stays readable (R4).
    """
    freq = session.execute(text("SELECT concept_id, COUNT(*) c FROM paperconcept GROUP BY concept_id")).all()
    keep = {r[0] for r in freq if int(r[1]) >= min_papers}
    concepts = session.exec(select(Concept)).all()
    nodes = [{"id": c.id, "name": c.name, "type": c.type} for c in concepts if c.id in keep]
    rows = session.execute(text(_CONCEPT_EDGES_SQL)).all()
    edges = [
        {"source": r[0], "target": r[1], "weight": int(r[2])}
        for r in rows
        if r[0] in keep and r[1] in keep
    ]
    return {"nodes": nodes, "edges": edges}
