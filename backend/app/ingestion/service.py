import json
from pathlib import Path

from sqlmodel import Session, select

from app.ingestion.dedup import normalize_title
from app.ingestion.pdf_parser import parse_pdf
from app.ingestion.sources import FetchedPaper
from app.models import AnalysisRun, Paper, Provider, Summary
from app.models.base import utcnow


def find_duplicate(
    session: Session,
    doi: str | None,
    arxiv_id: str | None,
    title: str | None,
) -> Paper | None:
    """Return an existing non-deleted Paper matching doi/arxiv_id/title, else None."""
    if doi:
        hit = session.exec(select(Paper).where(Paper.doi == doi)).first()
        if hit:
            return hit
    if arxiv_id:
        hit = session.exec(select(Paper).where(Paper.arxiv_id == arxiv_id)).first()
        if hit:
            return hit
    tn = normalize_title(title)
    if tn:
        hit = session.exec(
            select(Paper).where(Paper.title_norm == tn, Paper.is_deleted == False)  # noqa: E712
        ).first()
        if hit:
            return hit
    return None


def persist_fetched(
    session: Session,
    fetched: FetchedPaper,
    pdf_dir: Path,
    client=None,
    provider: Provider | None = None,
    model_id: str | None = None,
) -> Paper:
    """Dedup, parse PDF, optionally AI-summarize, and persist a FetchedPaper.

    AI summarization runs only when ``client``/``provider``/``model_id`` are all
    provided (graceful degradation when no provider is configured — R11).
    """
    existing = find_duplicate(session, fetched.doi, fetched.arxiv_id, fetched.title)
    paper = existing if existing is not None else Paper(source=fetched.source, source_ref=fetched.source_ref)

    paper.title = fetched.title or paper.title
    paper.authors_json = json.dumps(fetched.authors, ensure_ascii=False)
    paper.abstract = fetched.abstract or paper.abstract
    paper.doi = fetched.doi or paper.doi
    paper.arxiv_id = fetched.arxiv_id or paper.arxiv_id
    paper.year = fetched.year or paper.year
    paper.venue = fetched.venue or paper.venue
    paper.title_norm = normalize_title(paper.title)
    paper.updated_at = utcnow()

    if fetched.pdf_bytes:
        slug = fetched.arxiv_id or (fetched.doi or "").replace("/", "_") or fetched.source_ref or "paper"
        pdf_path = Path(pdf_dir) / f"{slug}.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(fetched.pdf_bytes)
        paper.pdf_path = str(pdf_path)
        text, conf = parse_pdf(pdf_path)
        paper.full_text = text or paper.full_text
        paper.parse_confidence = conf

    session.add(paper)
    session.commit()
    session.refresh(paper)

    if client is not None and provider is not None and model_id:
        _analyze(session, paper, client, provider, model_id)

    return paper


def _analyze(session: Session, paper: Paper, client, provider: Provider, model_id: str) -> None:
    from app.ai_ops.summarize import summarize_paper

    run = AnalysisRun(paper_id=paper.id, provider_id=provider.id, model=model_id)
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        content = summarize_paper(client, provider, model_id, paper.title, paper.abstract, paper.full_text)
        session.add(Summary(paper_id=paper.id, run_id=run.id, content_json=json.dumps(content, ensure_ascii=False)))
        run.status = "done"
    except Exception:  # noqa: BLE001 — analysis failure must not abort ingest
        run.status = "failed"
    run.finished_at = utcnow()
    session.add(run)
    session.commit()
