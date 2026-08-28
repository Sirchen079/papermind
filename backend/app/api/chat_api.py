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


class ConvPatch(BaseModel):
    title: str


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


def _parse_sources(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


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
        "你是一名科研助手，可以通过工具直接访问用户的论文库：search_library（按关键词检索论文）、"
        "get_paper（元数据 + 摘要 + 概念）、get_paper_full_text（精读某篇论文全文）、list_concepts、"
        "以及 find_related。**务必使用工具**让回答建立在论文库的真实内容之上——先检索再总结，"
        "先读论文再点评，不要凭空猜测。引用论文时使用其标题。回答简洁、具体。\n\n"
        "**始终用简体中文回答**，无论论文本身是何种语言；论文标题、专有名词、术语可保留原文。\n\n"
        f"当前论文库共有 {len(papers)} 篇论文。"
        f"已知概念：{concept_names or '（暂无）'}。"
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
    """System prompt + the full conversation history (compaction trims later)."""
    history = session.exec(
        select(Message).where(Message.conversation_id == conversation.id)
    ).all()
    msgs: list[dict] = [{"role": "system", "content": _system_prompt(session, user_message, hits)}]
    for m in history:
        msgs.append({"role": m.role, "content": m.content})
    return msgs


def _context_window(session: Session, provider: Provider, model_id: str) -> int | None:
    """Look up the model's context window so the agent can budget against it."""
    from app.models import Model

    row = session.exec(
        select(Model).where(
            Model.provider_id == provider.id, Model.model_id == model_id
        )
    ).first()
    return row.context_window if row else None


def _auto_title(text: str) -> str:
    """Derive a short conversation title from the first user message.

    Collapses whitespace and caps length so the sidebar stays readable. Returns
    "" for blank input (caller keeps the existing title in that case).
    """
    return " ".join((text or "").split())[:60]


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


@router.patch("/chat/conversations/{cid}")
def rename_conversation(cid: int, body: ConvPatch, session: Session = Depends(get_session)) -> dict:
    conv = session.get(Conversation, cid)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "title must not be empty")
    conv.title = title[:120]
    conv.updated_at = utcnow()
    session.add(conv)
    session.commit()
    return {"id": conv.id, "title": conv.title}


@router.delete("/chat/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, session: Session = Depends(get_session)) -> None:
    conv = session.get(Conversation, cid)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    # Message→conversation FK has no ON DELETE cascade and foreign_keys=ON, so
    # clear child rows first. Flush forces the message DELETEs to execute
    # before the parent row's — SQLAlchemy can't infer the ordering from a bare
    # FK (no relationship), so without this it may delete the conversation
    # first and trip the constraint.
    for m in session.exec(select(Message).where(Message.conversation_id == cid)).all():
        session.delete(m)
    session.flush()
    session.delete(conv)
    session.commit()


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
                "sources": _parse_sources(m.sources_json),
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

    first_message = (
        session.exec(select(Message).where(Message.conversation_id == cid)).first() is None
    )
    session.add(Message(conversation_id=cid, role="user", content=body.content))
    if first_message:
        conv.title = _auto_title(body.content) or conv.title
    conv.updated_at = utcnow()
    session.add(conv)
    session.commit()

    hits = _retrieve_hits(session, body.content)
    messages = _build_messages(session, conv, body.content, hits)
    sources = _sources_from_hits(hits)

    from app.agent.loop import run_agent

    content = ""
    tokens = 0
    for kind, payload in run_agent(
        client, provider, model_id, messages, session,
        context_window=_context_window(session, provider, model_id),
    ):
        if kind == "done":
            content, tokens = payload["content"], payload["tokens"]
        elif kind == "error":
            raise HTTPException(500, payload["message"])

    msg = Message(
        conversation_id=cid,
        role="assistant",
        content=content,
        model=model_id,
        tokens_used=tokens,
        sources_json=json.dumps(sources, ensure_ascii=False) if sources else None,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return {
        "role": "assistant",
        "content": msg.content,
        "model": model_id,
        "tokens": tokens,
        "sources": sources,
        "title": conv.title,
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

    first_message = (
        session.exec(select(Message).where(Message.conversation_id == cid)).first() is None
    )
    session.add(Message(conversation_id=cid, role="user", content=body.content))
    if first_message:
        conv.title = _auto_title(body.content) or conv.title
    conv.updated_at = utcnow()
    session.add(conv)
    session.commit()

    hits = _retrieve_hits(session, body.content)
    messages = _build_messages(session, conv, body.content, hits)
    sources = _sources_from_hits(hits)
    title = conv.title  # snapshot for the done frame (sidebar sync)

    def event_stream():
        from app.agent.loop import run_agent

        content = ""
        tokens = 0
        try:
            for kind, payload in run_agent(
                client, provider, model_id, messages, session,
                context_window=_context_window(session, provider, model_id),
            ):
                if kind == "tool":
                    yield _sse("tool", payload)
                elif kind == "delta":
                    content = payload["content"]
                    yield _sse("delta", {"content": content})
                elif kind == "done":
                    content, tokens = payload["content"], payload["tokens"]
                elif kind == "error":
                    yield _sse("error", payload)
                    return
            msg = Message(
                conversation_id=cid,
                role="assistant",
                content=content,
                model=model_id,
                tokens_used=tokens,
                sources_json=json.dumps(sources, ensure_ascii=False) if sources else None,
            )
            session.add(msg)
            session.commit()
            session.refresh(msg)
            yield _sse(
                "done",
                {
                    "content": content,
                    "model": model_id,
                    "tokens": tokens,
                    "sources": sources,
                    "title": title,
                },
            )
        except Exception as exc:  # noqa: BLE001 — never leave the client hanging mid-stream
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
