import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.config import get_settings
from app.ingestion.citation_key import normalize_citation_key
from app.ingestion.dedup import normalize_title
from app.ingestion.service import analyze_paper, persist_fetched
from app.ingestion.sources import FetchedPaper, fetch_arxiv, parse_bibtex, parse_ris
from app.models import (
    AnalysisRun,
    CollectionPaper,
    Concept,
    Paper,
    PaperChunk,
    PaperConcept,
    PaperLink,
    PaperTag,
    Provider,
    Summary,
    Suggestion,
)
from app.models.base import utcnow
from app.models.paper import parse_authors_json, parse_summary_json
from app.organization.service import paper_collections, paper_tags
from app.providers.client import ProviderClient
from app.reading.service import reading_summary

router = APIRouter()


class ArxivIn(BaseModel):
    arxiv_id: str


class BibtexIn(BaseModel):
    bibtex: str


class RisIn(BaseModel):
    ris: str


class ManualPaperIn(BaseModel):
    model_config = {"extra": "forbid"}

    citation_key: str | None = None
    title: str
    authors: list[str] | None = None
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None


class PaperPatchIn(BaseModel):
    model_config = {"extra": "forbid"}

    citation_key: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None


def _pdf_dir() -> "Path":
    from pathlib import Path

    return Path(get_settings().data_dir) / "pdfs"


def _public(p: Paper) -> dict:
    return {
        "id": p.id,
        "source": p.source,
        "source_ref": p.source_ref,
        "citation_key": p.citation_key,
        "title": p.title,
        "authors": parse_authors_json(p.authors_json),
        "abstract": p.abstract,
        "year": p.year,
        "venue": p.venue,
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "parse_confidence": p.parse_confidence,
    }


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _citation_key(value: str | None) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    if normalize_citation_key(text) is None:
        raise ValueError("invalid citation key")
    return text


def _ensure_unique_citation_key(session: Session, paper_id: int, key: str | None) -> None:
    if key is None:
        return
    row = session.exec(
        select(Paper).where(
            Paper.citation_key == key,
            Paper.id != paper_id,
            Paper.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is not None:
        raise ValueError("citation key already exists")


def _ensure_unique_paper_identifier(
    session: Session, paper_id: int, field: str, value: str | None, message: str
) -> None:
    if value is None:
        return
    column = getattr(Paper, field)
    row = session.exec(
        select(Paper).where(
            column == value,
            Paper.id != paper_id,
            Paper.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is not None:
        raise ValueError(message)


def _ensure_unique_title(session: Session, paper_id: int, title: str | None) -> None:
    title_norm = normalize_title(title)
    if title_norm is None:
        return
    row = session.exec(
        select(Paper).where(
            Paper.title_norm == title_norm,
            Paper.id != paper_id,
            Paper.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is not None:
        raise ValueError("paper title already exists")


def _summary_for(session: Session, paper_id: int) -> dict | None:
    row = session.exec(select(Summary).where(Summary.paper_id == paper_id)).first()
    if row is None or not row.content_json:
        return None
    return parse_summary_json(row.content_json)


def _concepts_for(session: Session, paper_id: int) -> list[dict]:
    """Concepts linked to a paper: [{name, type}], stable order."""
    links = session.exec(
        select(PaperConcept).where(PaperConcept.paper_id == paper_id)
    ).all()
    if not links:
        return []
    cids = [lc.concept_id for lc in links]
    concepts = session.exec(select(Concept).where(Concept.id.in_(cids))).all()
    by_id = {c.id: c for c in concepts}
    return [
        {"name": by_id[lc.concept_id].name, "type": by_id[lc.concept_id].type}
        for lc in links
        if lc.concept_id in by_id
    ]


def _analysis_for(session: Session, paper_id: int) -> dict | None:
    """Latest analysis run for a paper, so the detail view can distinguish
    "never analyzed" from "analysis failed: <reason>" instead of a blank summary."""
    row = session.exec(
        select(AnalysisRun).where(AnalysisRun.paper_id == paper_id).order_by(AnalysisRun.id.desc())
    ).first()
    if row is None:
        return None
    return {"status": row.status, "error": row.error, "model": row.model}


def _analysis_ctx(session: Session) -> tuple[ProviderClient, Provider, str] | None:
    """Pick the provider + model for ingestion analysis (summarize + extract).

    Delegates to the role-aware picker with the ``summary`` role, which honors a
    summary-tagged model on ANY enabled provider (not just the first) and falls
    back to the first enabled provider's first model. Returns None when nothing
    is configured, so AI analysis is skipped gracefully.
    """
    from app.providers.selection import pick_llm

    return pick_llm(session, "summary")


@router.get("/papers")
def list_papers(session: Session = Depends(get_session)) -> list[dict]:
    out = []
    for p in session.exec(select(Paper).where(Paper.is_deleted == False)):  # noqa: E712
        d = _public(p)
        d["has_summary"] = _summary_for(session, p.id) is not None
        d["reading"] = reading_summary(session, p.id)
        d["tags"] = paper_tags(session, p.id)
        d["collections"] = paper_collections(session, p.id)
        out.append(d)
    return out


@router.get("/papers/{pid}")
def get_paper(pid: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Paper, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, "paper not found")
    d = _public(p)
    d["summary"] = _summary_for(session, p.id)
    d["concepts"] = _concepts_for(session, p.id)
    d["analysis"] = _analysis_for(session, p.id)
    d["full_text"] = p.full_text
    d["reading"] = reading_summary(session, p.id)
    d["tags"] = paper_tags(session, p.id)
    d["collections"] = paper_collections(session, p.id)
    return d


@router.patch("/papers/{pid}")
def patch_paper(pid: int, body: PaperPatchIn, session: Session = Depends(get_session)) -> dict:
    p = session.get(Paper, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, "paper not found")

    fields = body.model_fields_set
    try:
        if "citation_key" in fields:
            key = _citation_key(body.citation_key)
            _ensure_unique_citation_key(session, pid, key)
            p.citation_key = key
        if "doi" in fields:
            doi = _optional_text(body.doi)
            _ensure_unique_paper_identifier(session, pid, "doi", doi, "doi already exists")
            p.doi = doi
        if "arxiv_id" in fields:
            arxiv_id = _optional_text(body.arxiv_id)
            _ensure_unique_paper_identifier(
                session, pid, "arxiv_id", arxiv_id, "arxiv id already exists"
            )
            p.arxiv_id = arxiv_id
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    if "title" in fields:
        p.title = _optional_text(body.title)
        p.title_norm = normalize_title(p.title)
    if "authors" in fields:
        p.authors_json = json.dumps(
            [str(author).strip() for author in (body.authors or []) if str(author).strip()],
            ensure_ascii=False,
        )
    if "abstract" in fields:
        p.abstract = _optional_text(body.abstract)
    if "year" in fields:
        p.year = body.year
    if "venue" in fields:
        p.venue = _optional_text(body.venue)
    p.updated_at = utcnow()
    session.add(p)
    session.commit()
    session.refresh(p)
    return _public(p)


@router.post("/papers/manual", status_code=201)
def create_manual_paper(body: ManualPaperIn, session: Session = Depends(get_session)) -> dict:
    title = _optional_text(body.title)
    if title is None:
        raise HTTPException(422, "title is required")

    try:
        citation_key = _citation_key(body.citation_key)
        _ensure_unique_citation_key(session, 0, citation_key)
        doi = _optional_text(body.doi)
        _ensure_unique_paper_identifier(session, 0, "doi", doi, "doi already exists")
        arxiv_id = _optional_text(body.arxiv_id)
        _ensure_unique_paper_identifier(session, 0, "arxiv_id", arxiv_id, "arxiv id already exists")
        _ensure_unique_title(session, 0, title)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    paper = Paper(
        source="manual",
        citation_key=citation_key,
        title=title,
        authors_json=json.dumps(
            [str(author).strip() for author in (body.authors or []) if str(author).strip()],
            ensure_ascii=False,
        ),
        abstract=_optional_text(body.abstract),
        year=body.year,
        venue=_optional_text(body.venue),
        doi=doi,
        arxiv_id=arxiv_id,
        title_norm=normalize_title(title),
        updated_at=utcnow(),
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return _public(paper)


@router.delete("/papers/{pid}", status_code=204)
def delete_paper(pid: int, session: Session = Depends(get_session)) -> None:
    """Soft-delete a paper and drop its RAG chunks.

    Rows are kept (is_deleted=True) so history/conversations referencing the id
    stay consistent, but the paper is hidden from the library, the graph, the
    agent tools, and retrieval.
    """
    p = session.get(Paper, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, "paper not found")
    p.is_deleted = True
    p.updated_at = utcnow()
    session.add(p)
    # Remove retrieval chunks so a deleted paper can't surface in chat RAG.
    for chunk in session.exec(select(PaperChunk).where(PaperChunk.paper_id == pid)).all():
        session.delete(chunk)
    # Detach concept links so the concept graph (and the agent's list_concepts /
    # find_related counts) no longer count a hidden paper.
    for link in session.exec(select(PaperConcept).where(PaperConcept.paper_id == pid)).all():
        session.delete(link)
    # Detach thesis/project links too. A hidden paper no longer appears in the
    # thesis workspace, so leaving invisible links would block later cleanup.
    for link in session.exec(select(PaperLink).where(PaperLink.paper_id == pid)).all():
        session.delete(link)
    for link in session.exec(select(PaperTag).where(PaperTag.paper_id == pid)).all():
        session.delete(link)
    for link in session.exec(select(CollectionPaper).where(CollectionPaper.paper_id == pid)).all():
        session.delete(link)
    for suggestion in session.exec(
        select(Suggestion).where(
            (Suggestion.paper_id == pid) | (Suggestion.related_paper_id == pid)
        )
    ).all():
        suggestion.status = "dismissed"
        session.add(suggestion)
    session.commit()


@router.post("/papers/{pid}/analyze")
def analyze(pid: int, session: Session = Depends(get_session)) -> dict:
    """Re-run AI analysis (summary + concepts) on an existing paper.

    Used after editing metadata, swapping the summary-role model, or when the
    first analysis failed. Requires a summary-role provider; 400 otherwise.
    """
    p = session.get(Paper, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, "paper not found")
    ctx = _analysis_ctx(session)
    if ctx is None:
        raise HTTPException(400, "no summary-role LLM provider configured")
    client, provider, model_id = ctx
    try:
        analyze_paper(session, p, client, provider, model_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.refresh(p)
    return {
        "id": p.id,
        "summary": _summary_for(session, p.id),
        "concepts": _concepts_for(session, p.id),
    }


@router.get("/papers/{pid}/related")
def related_papers(pid: int, session: Session = Depends(get_session)) -> list[dict]:
    """Discover related works outside the library via OpenAlex (free, no key)."""
    from app.knowledge.recommend import search_related

    p = session.get(Paper, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, "paper not found")
    return search_related(p.title or "")


@router.post("/papers/reindex")
def reindex_papers(session: Session = Depends(get_session)) -> dict:
    """Re-chunk + re-embed every paper for retrieval (RAG).

    Run this after configuring (or changing) the embedding-role model, or to
    pick up improved full-text parses. Returns a structured result so the UI can
    tell the user the *real* reason for a no-op (not configured vs. empty library
    vs. embed call failed), instead of reporting a false "未配置 embedding 模型".
    """
    from app.rag.index import reindex_library

    return reindex_library(session).as_dict()


@router.post("/papers/arxiv")
def ingest_arxiv(body: ArxivIn, session: Session = Depends(get_session)) -> dict:
    try:
        fetched = fetch_arxiv(body.arxiv_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"arxiv fetch failed: {exc}") from exc
    ctx = _analysis_ctx(session)
    paper = persist_fetched(
        session,
        fetched,
        pdf_dir=_pdf_dir(),
        client=ctx[0] if ctx else None,
        provider=ctx[1] if ctx else None,
        model_id=ctx[2] if ctx else None,
    )
    return _public(paper)


@router.post("/papers/bibtex")
def ingest_bibtex(body: BibtexIn, session: Session = Depends(get_session)) -> list[dict]:
    ctx = _analysis_ctx(session)
    out = []
    for fetched in parse_bibtex(body.bibtex):
        paper = persist_fetched(
            session,
            fetched,
            pdf_dir=_pdf_dir(),
            client=ctx[0] if ctx else None,
            provider=ctx[1] if ctx else None,
            model_id=ctx[2] if ctx else None,
        )
        out.append(_public(paper))
    return out


@router.post("/papers/ris")
def ingest_ris(body: RisIn, session: Session = Depends(get_session)) -> list[dict]:
    ctx = _analysis_ctx(session)
    out = []
    for fetched in parse_ris(body.ris):
        paper = persist_fetched(
            session,
            fetched,
            pdf_dir=_pdf_dir(),
            client=ctx[0] if ctx else None,
            provider=ctx[1] if ctx else None,
            model_id=ctx[2] if ctx else None,
        )
        out.append(_public(paper))
    return out


@router.post("/papers/pdf")
async def ingest_pdf(file: UploadFile = File(...), session: Session = Depends(get_session)) -> dict:
    data = await file.read()
    fetched = FetchedPaper(
        source="pdf",
        source_ref=file.filename,
        title=file.filename,
        pdf_bytes=data,
    )
    ctx = _analysis_ctx(session)
    paper = persist_fetched(
        session,
        fetched,
        pdf_dir=_pdf_dir(),
        client=ctx[0] if ctx else None,
        provider=ctx[1] if ctx else None,
        model_id=ctx[2] if ctx else None,
    )
    return _public(paper)
