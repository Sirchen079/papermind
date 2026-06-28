import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Concept, Conversation, Message, Paper, Skill
from app.models.base import utcnow
from app.providers.selection import pick_llm

router = APIRouter()


class MessageIn(BaseModel):
    content: str


def _sse(event: str, data: dict) -> str:
    """Encode one Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _library_context(session: Session) -> str:
    """A compact summary of the library injected as system context (RAG-lite).

    Full vector RAG over chunk embeddings arrives later; for now the assistant
    is grounded with paper/concept counts + recent titles (citation grounding
    principle: it can only reference papers it's told about).
    """
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    concepts = session.exec(select(Concept)).all()
    concept_names = ", ".join(c.name for c in concepts[:30])
    titles = "\n".join(f"- {p.title}" for p in papers[:20] if p.title)
    base = (
        "You are a research assistant discussing the user's paper library. "
        "Answer grounded in the library below; if you cite a paper, use its title. "
        f"The library has {len(papers)} paper(s). "
        f"Known concepts: {concept_names or '(none yet)'}.\n"
        f"Recent paper titles:\n{titles or '(none)'}"
    )
    # Inject enabled declarative skills (instruction/persona) — §6.5.
    skills = session.exec(select(Skill).where(Skill.enabled == True)).all()  # noqa: E712
    blocks = [
        f"[Active skill — {s.name}]\n{s.body}"
        for s in skills
        if s.type in ("instruction", "persona") and s.body
    ]
    if blocks:
        base += "\n\n" + "\n\n".join(blocks)
    return base


def _build_messages(session: Session, conversation: Conversation) -> list[dict]:
    history = session.exec(
        select(Message).where(Message.conversation_id == conversation.id)
    ).all()
    msgs: list[dict] = [{"role": "system", "content": _library_context(session)}]
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
            {"role": m.role, "content": m.content, "model": m.model} for m in msgs
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

    messages = _build_messages(session, conv)
    result = client.complete(provider, model_id, messages, request_kind="chat")
    msg = Message(
        conversation_id=cid,
        role="assistant",
        content=result.content,
        model=model_id,
        tokens_used=result.total_tokens,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return {"role": "assistant", "content": msg.content, "model": model_id, "tokens": result.total_tokens}


@router.post("/chat/conversations/{cid}/messages/stream")
def stream_message(cid: int, body: MessageIn, session: Session = Depends(get_session)):
    """Streaming variant of send_message — emits SSE deltas as the model writes.

    Frame protocol:
      event: delta  data: {"content": "..."}      — incremental token(s)
      event: done   data: {"content","model","tokens"} — final, persisted
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

    messages = _build_messages(session, conv)

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
            )
            session.add(msg)
            session.commit()
            session.refresh(msg)
            yield _sse("done", {"content": content, "model": model_id, "tokens": total_tokens})
        except Exception as exc:  # noqa: BLE001 — never leave the client hanging mid-stream
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
