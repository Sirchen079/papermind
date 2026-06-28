import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.config import get_settings
from app.ingestion.service import persist_fetched
from app.ingestion.sources import FetchedPaper, fetch_arxiv, parse_bibtex
from app.models import Model, Paper, Provider, Summary
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto

router = APIRouter()


class ArxivIn(BaseModel):
    arxiv_id: str


class BibtexIn(BaseModel):
    bibtex: str


def _pdf_dir() -> "Path":
    from pathlib import Path

    return Path(get_settings().data_dir) / "pdfs"


def _public(p: Paper) -> dict:
    return {
        "id": p.id,
        "source": p.source,
        "source_ref": p.source_ref,
        "title": p.title,
        "authors": json.loads(p.authors_json or "[]"),
        "abstract": p.abstract,
        "year": p.year,
        "venue": p.venue,
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "parse_confidence": p.parse_confidence,
    }


def _summary_for(session: Session, paper_id: int) -> dict | None:
    row = session.exec(select(Summary).where(Summary.paper_id == paper_id)).first()
    if row is None or not row.content_json:
        return None
    return json.loads(row.content_json)


def _analysis_ctx(session: Session) -> tuple[ProviderClient, Provider, str] | None:
    """Pick the first enabled provider + a summary-role (or first) model.

    Returns None when no provider/model is configured (AI is skipped).
    """
    provider = session.exec(select(Provider).where(Provider.enabled == True)).first()  # noqa: E712
    if provider is None:
        return None
    model = session.exec(select(Model).where(Model.provider_id == provider.id, Model.role_default == "summary")).first()
    if model is None:
        model = session.exec(select(Model).where(Model.provider_id == provider.id)).first()
    if model is None:
        return None
    client = ProviderClient(session_factory=lambda: session, crypto=get_crypto())
    return client, provider, model.model_id


@router.get("/papers")
def list_papers(session: Session = Depends(get_session)) -> list[dict]:
    out = []
    for p in session.exec(select(Paper).where(Paper.is_deleted == False)):  # noqa: E712
        d = _public(p)
        d["has_summary"] = _summary_for(session, p.id) is not None
        out.append(d)
    return out


@router.get("/papers/{pid}")
def get_paper(pid: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Paper, pid)
    if p is None or p.is_deleted:
        raise HTTPException(404, "paper not found")
    d = _public(p)
    d["summary"] = _summary_for(session, p.id)
    d["full_text"] = p.full_text
    return d


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
