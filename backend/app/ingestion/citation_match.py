"""Match PaperCitation rows against library papers (P8.3).

Runs after ingest: forward-matches the new paper's own references, and
backfills OTHER papers' unmatched references that point at the new paper.
Idempotent — matched rows are never recomputed.
"""

from sqlalchemy import func
from sqlmodel import Session, or_, select

from app.models import Paper, PaperCitation

# Confidence by match strategy: identifiers beat fuzzy titles.
_CONFIDENCE = {"doi": 0.95, "arxiv": 0.9, "title": 0.7}


def _find_target(session: Session, row: PaperCitation) -> tuple[Paper | None, str | None]:
    """First library paper matching a citation row, by doi → arxiv → title."""
    visible = Paper.is_deleted == False  # noqa: E712
    if row.ref_doi:
        hit = session.exec(
            select(Paper).where(visible, func.lower(Paper.doi) == row.ref_doi.lower())
        ).first()
        if hit:
            return hit, "doi"
    if row.ref_arxiv_id:
        hit = session.exec(
            select(Paper).where(visible, func.lower(Paper.arxiv_id) == row.ref_arxiv_id.lower())
        ).first()
        if hit:
            return hit, "arxiv"
    if row.ref_title_norm:
        hit = session.exec(
            select(Paper).where(visible, Paper.title_norm == row.ref_title_norm)
        ).first()
        if hit:
            return hit, "title"
    return None, None


def _strategy_for_row(row: PaperCitation, paper: Paper) -> str | None:
    """Which field of an unmatched row hits the given paper (doi → arxiv → title)."""
    if row.ref_doi and paper.doi and row.ref_doi.lower() == paper.doi.lower():
        return "doi"
    if row.ref_arxiv_id and paper.arxiv_id and row.ref_arxiv_id == paper.arxiv_id:
        return "arxiv"
    if row.ref_title_norm and paper.title_norm and row.ref_title_norm == paper.title_norm:
        return "title"
    return None


def match_citations_for_paper(session: Session, paper: Paper) -> int:
    """Match + backfill citations around one paper; returns rows updated.

    Forward: the paper's own unmatched citation rows find library targets.
    Reverse: other papers' unmatched rows that point at this paper get their
    target backfilled (covers "A cited B, B ingested later").
    """
    updated = 0

    rows = session.exec(
        select(PaperCitation).where(
            PaperCitation.source_paper_id == paper.id,
            PaperCitation.match_status == "unmatched",
        )
    ).all()
    for row in rows:
        target, strategy = _find_target(session, row)
        if target is None or target.id == paper.id:  # self-citation guard
            continue
        row.target_paper_id = target.id
        row.match_status = "matched"
        row.match_confidence = _CONFIDENCE[strategy]
        session.add(row)
        updated += 1

    conds = []
    if paper.doi:
        conds.append(func.lower(PaperCitation.ref_doi) == paper.doi.lower())
    if paper.arxiv_id:
        conds.append(func.lower(PaperCitation.ref_arxiv_id) == paper.arxiv_id.lower())
    if paper.title_norm:
        conds.append(PaperCitation.ref_title_norm == paper.title_norm)
    if conds:
        for row in session.exec(
            select(PaperCitation).where(
                PaperCitation.match_status == "unmatched",
                PaperCitation.source_paper_id != paper.id,
                or_(*conds),
            )
        ).all():
            strategy = _strategy_for_row(row, paper)
            if strategy is None:
                continue  # SQL `==` matched on case; field-level check didn't
            row.target_paper_id = paper.id
            row.match_status = "matched"
            row.match_confidence = _CONFIDENCE[strategy]
            session.add(row)
            updated += 1

    if updated:
        session.commit()
    return updated
