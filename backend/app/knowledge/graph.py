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
JOIN paper pa ON pa.id = a.paper_id AND pa.is_deleted = 0
JOIN paper pb ON pb.id = b.paper_id AND pb.is_deleted = 0
GROUP BY a.paper_id, b.paper_id
"""

_CONCEPT_EDGES_SQL = """
SELECT a.concept_id AS s, b.concept_id AS t, COUNT(DISTINCT a.paper_id) AS w
FROM paperconcept a
JOIN paperconcept b ON a.paper_id = b.paper_id AND a.concept_id < b.concept_id
JOIN paper p ON p.id = a.paper_id AND p.is_deleted = 0
GROUP BY a.concept_id, b.concept_id
"""


def paper_graph(session: Session) -> dict:
    """Nodes = papers; edges = pairs sharing >=1 concept (weight = shared count)."""
    counts = {
        int(row[0]): int(row[1])
        for row in session.execute(
            text(
                """
                SELECT pc.paper_id, COUNT(DISTINCT pc.concept_id) AS c
                FROM paperconcept pc
                JOIN paper p ON p.id = pc.paper_id AND p.is_deleted = 0
                GROUP BY pc.paper_id
                """
            )
        ).all()
    }
    nodes = [
        {"id": p.id, "title": p.title, "year": p.year, "count": counts.get(p.id, 0)}
        for p in session.exec(select(Paper).where(Paper.is_deleted == False))  # noqa: E712
    ]
    rows = session.execute(text(_PAPER_EDGES_SQL)).all()
    edges = [{"source": r[0], "target": r[1], "weight": int(r[2])} for r in rows]
    return {"nodes": nodes, "edges": edges}


def concept_graph(session: Session, min_papers: int = 1) -> dict:
    """Nodes = concepts appearing in >=min_papers papers; edges = co-occurrence + hierarchy.

    min_papers filters low-frequency concepts so the graph stays readable (R4).
    """
    freq = session.execute(
        text(
            """
            SELECT pc.concept_id, COUNT(DISTINCT pc.paper_id) c
            FROM paperconcept pc
            JOIN paper p ON p.id = pc.paper_id AND p.is_deleted = 0
            GROUP BY pc.concept_id
            """
        )
    ).all()
    keep = {r[0] for r in freq if int(r[1]) >= min_papers}
    counts = {int(r[0]): int(r[1]) for r in freq}
    concepts = session.exec(select(Concept)).all()
    nodes = [{"id": c.id, "name": c.name, "type": c.type, "count": counts.get(c.id, 0)} for c in concepts if c.id in keep]
    rows = session.execute(text(_CONCEPT_EDGES_SQL)).all()
    edges = [
        {"source": r[0], "target": r[1], "weight": int(r[2]), "edge_type": "cooccurrence"}
        for r in rows
        if r[0] in keep and r[1] in keep
    ]
    edges.extend(
        {
            "source": concept.parent_concept_id,
            "target": concept.id,
            "weight": 1,
            "edge_type": "hierarchy",
        }
        for concept in concepts
        if concept.id in keep and concept.parent_concept_id in keep
    )
    return {"nodes": nodes, "edges": edges}
