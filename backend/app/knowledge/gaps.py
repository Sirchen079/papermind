"""Deterministic research-gap aggregation (P9.3).

Three sources, no LLM (same philosophy as knowledge/suggest): matrix
limitations/future_work clustered by shared concept, hub concepts gone stale
(no recent papers), and high-rating/low-relevance papers (important but
off-topic). Output ordering is stable so the view is reproducible.
"""

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models import Concept, Paper, PaperConcept, PaperReadingState, ReviewMatrixEntry

HUB_THRESHOLD = 3
STALE_YEARS = 3


def _current_year() -> int:
    return datetime.now(timezone.utc).year


def _paper_ids_with_concepts(session: Session, paper_ids: set[int]) -> dict[int, list[str]]:
    if not paper_ids:
        return {}
    links = session.exec(
        select(PaperConcept).where(PaperConcept.paper_id.in_(paper_ids))
    ).all()
    concept_ids = {link.concept_id for link in links}
    names = {
        c.id: c.name
        for c in session.exec(select(Concept).where(Concept.id.in_(concept_ids))).all()
    }
    grouped: dict[int, list[str]] = {}
    for link in links:
        name = names.get(link.concept_id)
        if name:
            grouped.setdefault(link.paper_id, []).append(name)
    return {pid: sorted(names_) for pid, names_ in grouped.items()}


def _matrix_gaps(session: Session) -> list[dict]:
    """(a) Matrix limitations/future_work entries clustered by shared concept."""
    rows = session.exec(
        select(ReviewMatrixEntry, Paper)
        .join(Paper, Paper.id == ReviewMatrixEntry.paper_id)
        .where(Paper.is_deleted == False)  # noqa: E712
    ).all()
    by_paper: dict[int, dict] = {}
    for entry, paper in rows:
        texts = [
            t.strip()
            for field in ("limitations", "future_work")
            if (t := (getattr(entry, field) or "").strip())
        ]
        if texts:
            by_paper[paper.id] = {
                "title": paper.title,
                "texts": texts,
            }
    if not by_paper:
        return []

    concept_map = _paper_ids_with_concepts(session, set(by_paper))
    clusters: dict[str, list[int]] = {}
    for pid, concepts in concept_map.items():
        for concept in concepts:
            clusters.setdefault(concept, []).append(pid)

    gaps = []
    for concept in sorted(clusters):
        pids = sorted(clusters[concept])
        if len(pids) < 1:
            continue
        rationale = "；".join(
            f"《{by_paper[pid]['title']}》：{by_paper[pid]['texts'][0][:60]}"
            for pid in pids[:3]
        )
        gaps.append(
            {
                "type": "matrix_open_question",
                "title": f"「{concept}」相关论文遗留的局限与后续工作（{len(pids)} 篇）",
                "paper_ids": pids,
                "rationale": rationale,
            }
        )
    return gaps


def _stale_hub_gaps(session: Session) -> list[dict]:
    """(b) Hub concepts whose library papers are all older than STALE_YEARS."""
    rows = session.exec(
        select(PaperConcept, Paper)
        .join(Paper, Paper.id == PaperConcept.paper_id)
        .where(Paper.is_deleted == False)  # noqa: E712
    ).all()
    by_concept: dict[int, list[tuple[int, int | None]]] = {}
    for link, paper in rows:
        by_concept.setdefault(link.concept_id, []).append((paper.id, paper.year))
    if not by_concept:
        return []
    concepts = {
        c.id: c.name
        for c in session.exec(select(Concept).where(Concept.id.in_(by_concept))).all()
    }

    cutoff = _current_year() - STALE_YEARS
    gaps = []
    for cid in sorted(by_concept):
        entries = by_concept[cid]
        if len(entries) < HUB_THRESHOLD:
            continue
        years = [year for _pid, year in entries if year]
        if years and max(years) >= cutoff:
            continue  # active theme, not stale
        pids = sorted(pid for pid, _year in entries)
        name = concepts.get(cid) or f"#{cid}"
        gaps.append(
            {
                "type": "stale_hub",
                "title": f"「{name}」是核心主题但库内近 {STALE_YEARS} 年没有新论文",
                "paper_ids": pids,
                "rationale": f"{len(pids)} 篇库内论文涉及该主题，最新年份为 {max(years) if years else '未知'}，可关注该方向是否有新进展或复兴机会。",
            }
        )
    return gaps


def _off_topic_gaps(session: Session) -> list[dict]:
    """(c) High rating + low relevance: important to the field, off the thesis line."""
    rows = session.exec(
        select(PaperReadingState, Paper)
        .join(Paper, Paper.id == PaperReadingState.paper_id)
        .where(
            Paper.is_deleted == False,  # noqa: E712
            PaperReadingState.rating >= 4,
            PaperReadingState.relevance <= 2,
        )
    ).all()
    gaps = []
    for state, paper in sorted(rows, key=lambda pair: pair[1].id):
        gaps.append(
            {
                "type": "off_topic_gem",
                "title": f"《{paper.title or f'#{paper.id}'}》质量很高但离课题较远",
                "paper_ids": [paper.id],
                "rationale": f"评分 {state.rating}/5、相关度 {state.relevance}/5：值得考虑是否把研究方向向它倾斜，或明确排除并降低沉没成本。",
            }
        )
    return gaps


def research_gaps(session: Session) -> list[dict]:
    """Aggregate all three gap sources deterministically."""
    gaps: list[dict] = []
    gaps.extend(_matrix_gaps(session))
    gaps.extend(_stale_hub_gaps(session))
    gaps.extend(_off_topic_gaps(session))
    return gaps
