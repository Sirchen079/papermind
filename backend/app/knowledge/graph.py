"""Knowledge-graph construction (paper graph + concept graph + claims graph).

Edges are derived on query from PaperConcept co-occurrence (the source of
truth). For a local single-user library this is fast enough; materialized
incremental edges (spec F6/G7) are a future optimization for very large libs.
Paper-graph edges carry an ``edge_type``: ``concept`` (co-occurrence) or
``citation`` (matched PaperCitation rows, source → target).
"""
from sqlalchemy import text
from sqlmodel import Session, select

from app.models import Claim, ClaimRelation, Concept, Paper, PaperCitation
from app.models.claim import CLAIM_RELATION_TYPES

PAPER_EDGE_TYPES = {"concept", "citation"}

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


def paper_graph(session: Session, edge_types: list[str] | None = None) -> dict:
    """Nodes = papers; edges = ``concept`` co-occurrence and/or ``citation`` links.

    ``edge_types=None`` keeps the historical concept-only behavior; otherwise
    each requested type is included (weight = shared concepts for concept
    edges, 1 for citation edges, always source → target).
    """
    wanted = set(edge_types) if edge_types else {"concept"}
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
    edges: list[dict] = []
    if "concept" in wanted:
        rows = session.execute(text(_PAPER_EDGES_SQL)).all()
        edges.extend({"source": r[0], "target": r[1], "weight": int(r[2]), "edge_type": "concept"} for r in rows)
    if "citation" in wanted:
        # Matched rows always reference live papers: a soft-deleted source drops
        # its rows, and a soft-deleted target degrades rows back to unmatched.
        for row in session.exec(
            select(PaperCitation).where(PaperCitation.match_status == "matched")
        ).all():
            edges.append(
                {
                    "source": row.source_paper_id,
                    "target": row.target_paper_id,
                    "weight": 1,
                    "edge_type": "citation",
                }
            )
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


def claims_graph(session: Session, types: list[str] | None = None) -> dict:
    """Nodes = non-deleted claims on live papers; edges = ClaimRelation rows.

    ``types=None`` keeps every relation type; otherwise the requested subset
    of supports/contradicts/extends is included. Node labels carry the paper
    title so a claim is traceable back to its source.
    """
    wanted = set(types) if types else set(CLAIM_RELATION_TYPES)
    papers = {
        p.id: p.title or f"#{p.id}"
        for p in session.exec(select(Paper).where(Paper.is_deleted == False))  # noqa: E712
    }
    claims = session.exec(
        select(Claim).where(Claim.is_deleted == False)  # noqa: E712
    ).all()
    live = [c for c in claims if c.paper_id in papers]
    label = lambda c: f"【{papers[c.paper_id][:20]}】{c.text[:60]}"  # noqa: E731
    nodes = [
        {
            "id": c.id,
            "label": label(c),
            "text": c.text,
            "kind": c.kind,
            "source": c.source,
            "paper_id": c.paper_id,
            "paper_title": papers[c.paper_id],
        }
        for c in live
    ]
    live_ids = {c.id for c in live}
    edges = [
        {
            "source": r.claim_a_id,
            "target": r.claim_b_id,
            "weight": 1,
            "edge_type": r.type,
            "note": r.note,
        }
        for r in session.exec(select(ClaimRelation)).all()
        if r.claim_a_id in live_ids and r.claim_b_id in live_ids and r.type in wanted
    ]
    return {"nodes": nodes, "edges": edges}
