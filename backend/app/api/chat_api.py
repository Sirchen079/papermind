import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Concept, Conversation, Message, Paper, PaperChunk
from app.models.base import utcnow
from app.providers.selection import pick_llm

router = APIRouter()


class MessageIn(BaseModel):
    content: str


def _sse(event: str, data: dict) -> str:
    """Encode one Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _retrieve_hits(
    session: Session, user_message: str
) -> list[tuple[PaperChunk, float, Paper]]:
    """RAG retrieval: ranked ``(chunk, score, paper)`` triples for the question.

    Empty when no embedding model is configured or the query is blank.
    """
    from app.rag.index import retrieve

    if not (user_message or "").strip():
        return []
    hits: list[tuple[PaperChunk, float, Paper]] = []
    for chunk, score in retrieve(session, user_message):
        hits.append((chunk, score, session.get(Paper, chunk.paper_id)))
    return hits


def _sources_from_hits(
    hits: list[tuple[PaperChunk, float, Paper]], limit: int = 5
) -> list[dict]:
    """Deduplicated, capped source list for the UI (RAG provenance).

    One entry per paper (highest-scoring chunk wins), each with a short snippet
    surfaced as the chip tooltip.
    """
    sources: list[dict] = []
    seen: set[int] = set()
    for chunk, _score, paper in hits:
        pid = chunk.paper_id
        if pid in seen:
            continue
        seen.add(pid)
        title = (paper.title if paper else None) or f"#{pid}"
        snippet = " ".join(chunk.text.split())  # collapse whitespace/newlines
        if len(snippet) > 160:
            snippet = snippet[:157] + "…"
        sources.append({"paper_id": pid, "title": title, "snippet": snippet})
        if len(sources) >= limit:
            break
    return sources


def _system_prompt(
    session: Session, user_message: str, hits: list[tuple[PaperChunk, float, Paper]]
) -> str:
    """Ground the assistant in the library (RAG).

    Injects retrieved passages with their source titles when available (citation
    grounding — the assistant can only reference papers it's shown), else falls
    back to recent titles + concept counts. Active skills are appended per the
    trigger rules (app.skills.activation).
    """
    from app.skills.activation import select_for_chat

    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    concepts = session.exec(select(Concept)).all()
    concept_names = ", ".join(c.name for c in concepts[:30])
    base = (
        "You are a research assistant discussing the user's paper library. "
        "Answer grounded in the context below; if you cite a paper, use its title. "
        f"The library has {len(papers)} paper(s). "
        f"Known concepts: {concept_names or '(none yet)'}."
    )

    if hits:
        lines = []
        for chunk, _score, paper in hits:
            title = (paper.title if paper else None) or f"#{chunk.paper_id}"
            lines.append(f"[{title}]\n{chunk.text}")
        base += "\n\nRelevant passages from your library:\n" + "\n\n".join(lines)
    else:
        titles = "\n".join(f"- {p.title}" for p in papers[:20] if p.title)
        if titles:
            base += f"\n\nRecent paper titles:\n{titles}"

    skills = select_for_chat(session, user_message)
    blocks = [f"[Active skill — {s.name}]\n{s.body}" for s in skills]
    if blocks:
        base += "\n\n" + "\n\n".join(blocks)
    return base


def _build_messages(
    session: Session,
    conversation: Conversation,
    user_message: str,
    hits: list[tuple[PaperChunk, float, Paper]],
) -> list[dict]:
    history = session.exec(
        select(Message).where(Message.conversation_id == conversation.id)
    ).all()
    msgs: list[dict] = [{"role": "system", "content": _system_prompt(session, user_message, hits)}]
    for m in history[-10:]:
        msgs.append({"role": m.role, "content": m.content})
    return msgs


@router.post("/chat/conversations")
def create_conversation(session: Session = Depends(get_session)) -> dict:
    c = Conversation(title="New conversation")
    session.add(c)
    session.commit()
    session.refresh(c)
    return {"id": c.id, "title": c.title}


@router.get("/chat/conversations")
def list_conversations(session: Session = Depends(get_session)) -> list[dict]:
    return [{"id": c.id, "title": c.title} for c in session.exec(select(Conversation)).all()]


@router.get("/chat/conversations/{cid}")
def get_conversation(cid: int, session: Session = Depends(get_session)) -> dict:
    conv = session.get(Conversation, cid)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    msgs = session.exec(select(Message).where(Message.conversation_id == cid)).all()
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "model": m.model,
                "sources": json.loads(m.sources_json) if m.sources_json else [],
            }
            for m in msgs
        ],
    }


@router.post("/chat/conversations/{cid}/messages")
def send_message(cid: int, body: MessageIn, session: Session = Depends(get_session)) -> dict:
    conv = session.get(Conversation, cid)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    ctx = pick_llm(session, "chat")
    if ctx is None:
        raise HTTPException(400, "no LLM provider configured")
    client, provider, model_id = ctx

    session.add(Message(conversation_id=cid, role="user", content=body.content))
    conv.updated_at = utcnow()
    session.add(conv)
    session.commit()

    hits = _retrieve_hits(session, body.content)
    messages = _build_messages(session, conv, body.content, hits)
    sources = _sources_from_hits(hits)
    result = client.complete(provider, model_id, messages, request_kind="chat")
    msg = Message(
        conversation_id=cid,
        role="assistant",
        content=result.content,
        model=model_id,
        tokens_used=result.total_tokens,
        sources_json=json.dumps(sources, ensure_ascii=False) if sources else None,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return {
        "role": "assistant",
        "content": msg.content,
        "model": model_id,
        "tokens": result.total_tokens,
        "sources": sources,
    }


@router.post("/chat/conversations/{cid}/messages/stream")
def stream_message(cid: int, body: MessageIn, session: Session = Depends(get_session)):
    """Streaming variant of send_message — emits SSE deltas as the model writes.

    Frame protocol:
      event: delta  data: {"content": "..."}      — incremental token(s)
      event: done   data: {"content","model","tokens","sources"} — final, persisted
      event: error  data: {"message": "..."}      — mid-stream failure
    """
    conv = session.get(Conversation, cid)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    ctx = pick_llm(session, "chat")
    if ctx is None:
        raise HTTPException(400, "no LLM provider configured")
    client, provider, model_id = ctx

    session.add(Message(conversation_id=cid, role="user", content=body.content))
    conv.updated_at = utcnow()
    session.add(conv)
    session.commit()

    hits = _retrieve_hits(session, body.content)
    messages = _build_messages(session, conv, body.content, hits)
    sources = _sources_from_hits(hits)

    def event_stream():
        collected: list[str] = []
        total_tokens = 0
        try:
            for ev in client.stream_complete(provider, model_id, messages, request_kind="chat"):
                if ev.delta:
                    collected.append(ev.delta)
                    yield _sse("delta", {"content": ev.delta})
                if ev.done:
                    total_tokens = ev.total_tokens
            content = "".join(collected)
            msg = Message(
                conversation_id=cid,
                role="assistant",
                content=content,
                model=model_id,
                tokens_used=total_tokens,
                sources_json=json.dumps(sources, ensure_ascii=False) if sources else None,
            )
            session.add(msg)
            session.commit()
            session.refresh(msg)
            yield _sse(
                "done",
                {"content": content, "model": model_id, "tokens": total_tokens, "sources": sources},
            )
        except Exception as exc:  # noqa: BLE001 — never leave the client hanging mid-stream
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
