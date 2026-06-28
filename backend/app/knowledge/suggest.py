"""Proactive suggestion generation from the knowledge graph.

Suggestions are derived deterministically from the user's own concept graph
(no LLM, no network), so they're reproducible, cheap, and grounded only in
what the assistant has actually extracted. Two kinds today:

  - concept_link: two library papers share concept(s) → "these are related".
  - concept_hub:  one concept spans N papers → "this is a central theme".

Generation is idempotent via ``dedup_key``: re-scanning after ingest never
creates duplicate suggestions (it only surfaces new connections).
"""
import json

from sqlmodel import Session, select

from app.models import Concept, Paper, PaperConcept, Suggestion

HUB_THRESHOLD = 3  # a concept needs this many papers to be flagged a hub


def _exists(session: Session, dedup_key: str) -> bool:
    return session.exec(
        select(Suggestion.id).where(Suggestion.dedup_key == dedup_key)
    ).first() is not None


def _add(session: Session, **fields) -> bool:
    """Insert a suggestion unless its dedup_key already exists. Returns created?."""
    key = fields.get("dedup_key")
    if key and _exists(session, key):
        return False
    session.add(Suggestion(**fields))
    return True


def _shared_concepts(session: Session, paper_id: int) -> dict[int, list[str]]:
    """Map related_paper_id -> [shared concept names] for papers sharing ≥1 concept."""
    # concept ids attached to the subject paper
    my_concepts = {
        row.concept_id
        for row in session.exec(select(PaperConcept).where(PaperConcept.paper_id == paper_id)).all()
    }
    if not my_concepts:
        return {}
    cid_to_name = {
        c.id: c.name
        for c in session.exec(select(Concept).where(Concept.id.in_(my_concepts))).all()
    }
    related: dict[int, set[int]] = {}
    rows = session.exec(select(PaperConcept).where(PaperConcept.concept_id.in_(my_concepts))).all()
    for row in rows:
        if row.paper_id == paper_id:
            continue
        related.setdefault(row.paper_id, set()).add(row.concept_id)
    return {
        pid: sorted(cid_to_name[c] for c in cids if c in cid_to_name)
        for pid, cids in related.items()
    }


def concept_links_for_paper(session: Session, paper: Paper) -> int:
    """Generate concept_link suggestions connecting ``paper`` to related papers.

    Returns the number of new suggestions created.
    """
    shared = _shared_concepts(session, paper.id)
    created = 0
    for related_id, concepts in shared.items():
        related_paper = session.get(Paper, related_id)
        related_title = related_paper.title if related_paper else f"#{related_id}"
        a, b = sorted((paper.id, related_id))
        dedup_key = f"concept_link:{a}:{b}"
        created += _add(
            session,
            kind="concept_link",
            title=f"“{paper.title}” connects to “{related_title}”",
            detail_json=json.dumps(
                {"shared_concepts": concepts, "count": len(concepts)}, ensure_ascii=False
            ),
            paper_id=a,
            related_paper_id=b,
            weight=float(len(concepts)),
            dedup_key=dedup_key,
        )
    if created:
        session.commit()
    return created


def concept_hubs(session: Session) -> int:
    """Flag concepts spanning ≥HUB_THRESHOLD papers as central themes."""
    counts: dict[int, int] = {}
    for row in session.exec(select(PaperConcept)).all():
        counts[row.concept_id] = counts.get(row.concept_id, 0) + 1
    hub_ids = [cid for cid, n in counts.items() if n >= HUB_THRESHOLD]
    created = 0
    for cid in hub_ids:
        concept = session.get(Concept, cid)
        if concept is None:
            continue
        created += _add(
            session,
            kind="concept_hub",
            title=f"“{concept.name}” is a central theme in your library",
            detail_json=json.dumps(
                {"concept": concept.name, "papers": counts[cid]}, ensure_ascii=False
            ),
            weight=float(counts[cid]),
            dedup_key=f"concept_hub:{cid}",
        )
    if created:
        session.commit()
    return created


def generate_for_paper(session: Session, paper: Paper) -> int:
    """All suggestion types relevant to a freshly-analyzed paper."""
    return concept_links_for_paper(session, paper)


def generate_all(session: Session) -> int:
    """Scan the whole library — used by the manual 'scan library' endpoint."""
    created = 0
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    for p in papers:
        created += concept_links_for_paper(session, p)
    created += concept_hubs(session)
    return created
