"""Chunk + embed paper text for retrieval (RAG), and query-time retrieval.

Indexing runs during ingest when an ``embedding``-role model is configured
(see app.providers.selection.pick_llm). Retrieval is invoked from chat to
ground answers in the user's own papers. Both degrade gracefully to a no-op
when no embedding model is set.

Observability contract (do NOT regress this): ``index_paper`` *raises* when the
embedding call itself fails, and returns 0 only for genuine skips (no model
configured, or the paper has no text). Swallowing embed errors here is what made
reindex lie "未配置 embedding 模型" for every failure mode — see ``ReindexResult``.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from sqlmodel import Session, select, func

from app.models import Paper, PaperChunk
from app.providers.selection import pick_llm
from app.rag.chunker import chunk_text
from app.rag.vector import deserialize, serialize, top_k

CHUNK_TARGET = 1000
RETRIEVE_K = 5


@dataclass
class ReindexResult:
    """Structured outcome of a library re-index, so the UI can tell the user the
    REAL reason instead of collapsing every zero-chunk case to "not configured".

    - ``configured``: an embedding-role model on an enabled provider exists.
    - ``papers``: non-deleted papers considered.
    - ``indexed_papers`` / ``chunks``: papers that yielded chunks, and chunk total.
    - ``skipped_no_text``: papers with no abstract and no full text (nothing to embed).
    - ``error``: first embedding error encountered (endpoint/auth/model). The run
      stops at the first error — an embed failure is almost always endpoint-level,
      so continuing would just hammer a dead/wrong endpoint.
    """

    configured: bool
    papers: int
    indexed_papers: int
    chunks: int
    skipped_no_text: int
    error: str | None

    def as_dict(self) -> dict:
        return asdict(self)


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
    Returns the number of chunks stored; 0 for genuine skips (no embedding model
    configured, or the paper has no text). **Raises** when the embedding call
    itself fails or returns a malformed response — callers that must not abort
    (ingest) wrap this in try/except; callers that report to the user (reindex)
    surface the message. Existing chunks are only dropped after embed succeeds,
    so a failure never wipes what was already indexed.
    """
    if client is None or provider is None or model_id is None:
        ctx = pick_llm(session, "embedding")
        if ctx is None:
            return 0
        client, provider, model_id = ctx

    texts = _chunk_texts(paper)
    if not texts:
        return 0

    embeddings = client.embed(provider, model_id, texts, request_kind="embedding")
    if len(embeddings) != len(texts):  # provider returned a partial / odd shape
        raise RuntimeError(
            f"embedding model returned {len(embeddings)} vectors for {len(texts)} chunks"
        )

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


def reindex_library(session: Session) -> ReindexResult:
    """Re-chunk + re-embed every non-deleted paper.

    Returns a structured ``ReindexResult`` so callers can distinguish "not
    configured" from "configured but nothing to index" from "embed call failed"
    — previously all three collapsed to ``0`` and the UI reported a false
    "未配置 embedding 模型".
    """
    paper_count = session.exec(
        select(func.count(Paper.id)).where(Paper.is_deleted == False)  # noqa: E712
    ).one()
    ctx = pick_llm(session, "embedding")
    if ctx is None:
        return ReindexResult(
            configured=False, papers=paper_count,
            indexed_papers=0, chunks=0, skipped_no_text=0, error=None,
        )
    client, provider, model_id = ctx

    result = ReindexResult(
        configured=True, papers=paper_count,
        indexed_papers=0, chunks=0, skipped_no_text=0, error=None,
    )
    for paper in session.exec(select(Paper).where(Paper.is_deleted == False)).all():  # noqa: E712
        try:
            n = index_paper(session, paper, client, provider, model_id)
        except Exception as exc:  # noqa: BLE001 — record + stop; endpoint-level, no point retrying
            result.error = f"{type(exc).__name__}: {exc}"
            break
        if n == 0:
            result.skipped_no_text += 1
        else:
            result.indexed_papers += 1
            result.chunks += n
    return result


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
    ctx = pick_llm(session, "embedding")
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
