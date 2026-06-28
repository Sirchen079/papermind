from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models import Concept, Conversation, Message, Paper
from app.models.base import utcnow
from app.providers.selection import pick_llm

router = APIRouter()


class MessageIn(BaseModel):
    content: str


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
    return (
        "You are a research assistant discussing the user's paper library. "
        "Answer grounded in the library below; if you cite a paper, use its title. "
        f"The library has {len(papers)} paper(s). "
        f"Known concepts: {concept_names or '(none yet)'}.\n"
        f"Recent paper titles:\n{titles or '(none)'}"
    )


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
