"""Chunk + embed paper text for retrieval (RAG), and query-time retrieval.

Indexing runs during ingest when an ``embedding``-role model is configured
(see app.providers.selection.pick_llm). Retrieval is invoked from chat to
ground answers in the user's own papers. Both degrade gracefully to a no-op
when no embedding model is set.
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.models import Paper, PaperChunk
from app.providers.selection import pick_llm
from app.rag.chunker import chunk_text
from app.rag.vector import deserialize, serialize, top_k

CHUNK_TARGET = 1000
RETRIEVE_K = 5


def _chunk_texts(paper: Paper) -> list[str]:
    """Build the chunk texts for a paper: a metadata chunk + full-text chunks.

    The metadata chunk (title + abstract) ensures even papers without parsed
    full text (e.g. BibTeX-only entries) are retrievable.
    """
    texts: list[str] = []
    meta = "\n\n".join(p for p in (paper.title, paper.abstract) if p)
    if meta:
        texts.append(meta)
    if paper.full_text:
        texts.extend(chunk_text(paper.full_text, target=CHUNK_TARGET))
    return texts


def index_paper(
    session: Session,
    paper: Paper,
    client=None,
    provider=None,
    model_id: str | None = None,
) -> int:
    """Chunk + embed a paper, replacing any existing chunks (re-index).

    Resolves the ``embedding``-role model itself when a client isn't supplied.
    Returns the number of chunks stored; 0 when no embedding model is
    configured, the paper has no text, or the embedding call fails.
    """
    if client is None or provider is None or model_id is None:
        ctx = pick_llm(session, "embedding", strict=True)
        if ctx is None:
            return 0
        client, provider, model_id = ctx

    texts = _chunk_texts(paper)
    if not texts:
        return 0

    try:
        embeddings = client.embed(provider, model_id, texts, request_kind="embedding")
    except Exception:  # noqa: BLE001 — embedding must never abort ingest
        return 0
    if len(embeddings) != len(texts):  # provider returned a partial / odd shape
        return 0

    # Embedding succeeded — only NOW drop the old chunks. Deleting before the
    # embed call left pending deletes that the caller's next commit would flush,
    # wiping a paper's chunks whenever the embedding provider was down.
    for old in session.exec(select(PaperChunk).where(PaperChunk.paper_id == paper.id)).all():
        session.delete(old)

    for i, (text, vec) in enumerate(zip(texts, embeddings)):
        session.add(
            PaperChunk(
                paper_id=paper.id,
                ordinal=i,
                text=text,
                embedding=serialize(vec),
                embedding_model=model_id,
            )
        )
    session.commit()
    return len(texts)


def reindex_library(session: Session) -> int:
    """Re-chunk + re-embed every non-deleted paper. Returns chunks stored."""
    ctx = pick_llm(session, "embedding", strict=True)
    if ctx is None:
        return 0
    client, provider, model_id = ctx
    total = 0
    for paper in session.exec(select(Paper).where(Paper.is_deleted == False)).all():  # noqa: E712
        total += index_paper(session, paper, client, provider, model_id)
    return total


def retrieve(
    session: Session, query: str, k: int = RETRIEVE_K
) -> list[tuple[PaperChunk, float]]:
    """Return the ``k`` chunks most relevant to ``query`` by cosine.

    Only chunks embedded with the active embedding model are considered (so a
    model switch never compares incompatible vectors). Empty when no embedding
    model is configured, the query is blank, or no matching chunks exist.
    """
    query = (query or "").strip()
    if not query:
        return []
    ctx = pick_llm(session, "embedding", strict=True)
    if ctx is None:
        return []
    client, provider, model_id = ctx
    try:
        qvec = client.embed(provider, model_id, [query], request_kind="embedding")[0]
    except Exception:  # noqa: BLE001 — retrieval is best-effort
        return []

    rows = session.exec(select(PaperChunk).where(PaperChunk.embedding_model == model_id)).all()
    if not rows:
        return []
    candidates = [(row, list(deserialize(row.embedding))) for row in rows]
    return top_k(qvec, candidates, k)
