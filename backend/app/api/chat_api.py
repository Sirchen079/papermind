import json
from threading import Event, Lock
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import get_session
from app.agent.clarification import ClarificationResponse, answer_content, question_content
from app.agent.provenance import merge_sources, public_sources, topic_sources
from app.agent.presentation import public_updates, research_messages
from app.agent.document_revisions import public_revision, revise_document, latest_turn, resume_with_revisions, revision_context
from app.models import (
    Concept,
    Conversation,
    Message,
    Paper,
    PaperChunk,
    PaperExcerpt,
    PaperNote,
    Provider,
    ReviewMatrixEntry,
    Summary,
)
from app.models.base import utcnow
from app.models.paper import parse_authors_json, parse_summary_json
from app.providers.selection import pick_llm

from app.agent.attachments import Attachment, MAX_FILE_BYTES, attach_content, prepare_attachment

router = APIRouter()


@router.get('/chat/saved-documents')
def saved_chat_documents(q:str='',offset:int=0,limit:int=20,include_previous_versions:bool=False,session:Session=Depends(get_session)):
    from app.agent.saved_documents import list_documents
    return list_documents(session,q,offset,limit,include_previous_versions)


@router.get('/chat/saved-documents/{message_id}')
def saved_chat_document(message_id:int,filename:str,session:Session=Depends(get_session)):
    from app.agent.saved_documents import get_document
    try:
        record = get_document(session,message_id,filename)
        return {**record, **public_sources(record['sources'])}
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from exc


@router.get('/chat/documents/{filename}')
def download_chat_document(filename: str):
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.config import get_settings
    root = (Path(get_settings().data_dir) / 'exports').resolve()
    path = (root / filename).resolve()
    if path.parent != root or path.suffix.lower() not in {'.md', '.txt'} or not path.is_file():
        raise HTTPException(404, 'document not found')
    return FileResponse(path, filename=path.name)

_cancel_events: dict[tuple[str, int], Event] = {}
_active_turns: set[tuple[str, int]] = set()
_turn_lock = Lock()


class DocumentRevisionIn(BaseModel):
    filename: str = Field(min_length=1,max_length=255)
    content: str = Field(min_length=1,max_length=1_000_000)


class DocumentEditApplyIn(BaseModel):
    replacement: str = Field(max_length=1_000_000)


@router.post('/chat/conversations/{cid}/documents/proposals/{proposal_id}/apply')
def adopt_document_edit(cid:int,proposal_id:str,body:DocumentEditApplyIn,session:Session=Depends(get_session)):
    from app.agent.document_edits import apply_document_edit
    with _turn_lock:
        if _turn_key(session,cid) in _active_turns:
            raise HTTPException(409,'本轮仍在生成，修改内容已保留，请完成后保存。')
        return apply_document_edit(session,cid,proposal_id,body.replacement)


@router.post('/chat/conversations/{cid}/documents/revisions')
def save_document_revision(cid:int,body:DocumentRevisionIn,session:Session=Depends(get_session)):
    with _turn_lock:
        if _turn_key(session,cid) in _active_turns:
            raise HTTPException(409,'本轮仍在生成，编辑内容已保留，请完成后保存修订版。')
        return revise_document(session,cid,body.filename,body.content)


@router.post('/chat/conversations/{cid}/messages/{message_id}/document')
def save_answer_document(cid:int,message_id:int,session:Session=Depends(get_session)):
    from app.agent.document_revisions import capture_answer
    with _turn_lock:
        if _turn_key(session,cid) in _active_turns:
            raise HTTPException(409,'本轮仍在生成，请在回答结束后保存文档。')
        return capture_answer(session,cid,message_id)


def pick_chat_model(session, config_id):
    if config_id is None:
        return pick_llm(session, 'chat')
    from app.models import Model
    from app.providers.client import ProviderClient
    from app.providers.shared import resolve
    model = session.get(Model, config_id)
    from app.providers.purposes import is_reranker
    provider = session.get(Provider, model.provider_id) if model else None
    if not model or model.role_default == 'embedding' or is_reranker(session, model) or not provider or provider.is_deleted or not provider.enabled:
        raise HTTPException(422, '所选模型不可用，请重新选择模型')
    try:
        actual, crypto = resolve(provider)
    except LookupError as exc:
        raise HTTPException(422, '模型连接已不可用，请检查设置') from exc
    if not actual.enabled:
        raise HTTPException(422, '模型连接已停用')
    engine = session.get_bind()
    return ProviderClient(lambda: Session(engine), crypto), actual, model.model_id


def validate_images(session, ctx, attachments):
    if not any(a.kind == 'image' for a in attachments) or ctx is None:
        return
    from app.models import Model
    _, provider, model_id = ctx
    row = session.exec(select(Model).where(Model.provider_id == provider.id, Model.model_id == model_id)).first()
    if row is not None and row.supports_images is False:
        raise HTTPException(422, '当前模型已设为不支持图片，请选择支持图片的模型；附件和草稿会保留。')


@router.post('/chat/attachments')
async def upload_attachment(file: UploadFile = File(...)):
    raw = await file.read(MAX_FILE_BYTES + 1)
    await file.close()
    try:
        return prepare_attachment(file.filename or '附件', raw).model_dump()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/chat/models')
def chat_models(session: Session = Depends(get_session)):
    from app.models import Model
    from app.providers.purposes import is_reranker
    default = pick_llm(session, 'chat')
    rows = []
    for model, provider in session.exec(select(Model, Provider).join(Provider, Model.provider_id == Provider.id)
            .where(Provider.enabled == True, Provider.is_deleted == False)).all():
        if model.role_default == 'embedding' or is_reranker(session, model):
            continue
        rows.append({'id': model.id, 'name': model.display_name or model.model_id,
                     'provider': provider.name, 'context_window': _context_window(session, provider, model.model_id),
                     'reasoning_effort': model.reasoning_effort, 'supports_images': model.supports_images,
                     'is_default': bool(default and default[1].id == provider.id and default[2] == model.model_id)})
    return rows


@router.post('/chat/conversations/{cid}/stop')
def stop_turn(cid: int, session: Session = Depends(get_session)):
    if session.get(Conversation, cid) is None:
        raise HTTPException(404, 'conversation not found')
    with _turn_lock:
        event = _cancel_events.get(_turn_key(session, cid))
        if event:
            event.set()
    return {'stopping': event is not None}


def _turn_key(session: Session, cid: int):
    bind = session.get_bind()
    engine = getattr(bind, 'engine', bind)
    return str(engine.url), cid


def _release_turn(cid: int, session: Session):
    with _turn_lock:
        _active_turns.discard(_turn_key(session, cid))
        _cancel_events.pop(_turn_key(session, cid), None)


def _fail_turn(session: Session, message_id: int, error: str, state: dict | None = None):
    session.rollback()
    row = session.get(Message, message_id)
    if row is not None and row.delivery_status == "pending":
        row.delivery_status = "failed"
        row.error_message = error
        if state:
            row.agent_state_json = json.dumps(state, ensure_ascii=False)
            if state.get("sources"):
                row.sources_json = json.dumps(state["sources"], ensure_ascii=False)
        session.add(row)
        session.commit()


def _save_progress(session: Session, user_row: Message, tools: list, updates: list, sources: list):
    """Journal visible work without pretending it is a completed answer or resumable context."""
    state = json.loads(user_row.agent_state_json or '{}')
    user_row.agent_state_json = json.dumps({**state, 'tools': tools, 'updates': updates}, ensure_ascii=False)
    user_row.sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
    session.add(user_row)
    session.commit()


# T5：论文上下文问答——selected_text 与各上下文小节的长度上限（字符）。
SELECTED_TEXT_MAX = 4000
_PAPER_CONTEXT_SECTION_MAX = 2000
_PAPER_CONTEXT_TOTAL_MAX = 9000


class MessageIn(BaseModel):
    workflow: Literal['general', 'literature-synthesis', 'review-revision'] = 'general'
    paper_ids: list[int] | None = Field(default=None, max_length=100)
    review_evidence: bool = False
    attachments: list[Attachment] = Field(default_factory=list, max_length=4)
    model_config_id: int | None = None
    content: str = ""
    retry_message_id: int | None = None
    clarification_response: ClarificationResponse | None = None
    skill_ids: list[int] = Field(default_factory=list, max_length=20)
    paper_id: int | None = None
    selected_text: str | None = Field(default=None, max_length=SELECTED_TEXT_MAX)


class ConvPatch(BaseModel):
    paper_ids: list[int] | None = Field(default=None, max_length=100)
    title: str | None = None
    paper_id: int | None = None


class ConvCreate(BaseModel):
    paper_ids: list[int] | None = Field(default=None, max_length=100)
    paper_id: int | None = None


def _conversation_papers(conv):
    return json.loads(conv.paper_ids_json or '[]') or ([conv.paper_id] if conv.paper_id else [])


def _validate_papers(session, ids):
    ids = list(dict.fromkeys(ids))
    for pid in ids:
        paper = session.get(Paper, pid)
        if paper is None or paper.is_deleted:
            raise HTTPException(404, f"论文 #{pid} 不存在或已移除，请重新选择")
    return ids


def _group_context(session, ids):
    roster, blocks = [], []
    budget = max(120, 18000 // max(1, len(ids)))
    for pid in ids:
        paper = session.get(Paper, pid)
        if paper is None or paper.is_deleted:
            roster.append(f"paper_id={pid}：已移除，当前不可读取")
            continue
        ready = bool((paper.full_text or '').strip())
        roster.append(f"paper_id={pid}：《{(paper.title or '无标题')[:200]}》；{'全文已就绪' if ready else '暂无可读全文，可使用摘要和笔记'}")
        block = _paper_context(session, pid, None)
        if paper.abstract:
            block = f"摘要：{paper.abstract[:1500]}\n" + block
        blocks.append(f"[paper_id={pid}]\n" + _clip(block, budget))
    return ('[用户选择的论文讨论范围]\n' + '\n'.join(roster)
            + '\n优先围绕以上论文持续讨论，按需要使用 get_paper_full_text 读取对应 paper_id 的全文。'
            '比较或引用具体结论时注明论文标题，区分论文结论与你的推断；需要外部资料时说明其不属于所选论文。'
            '可以讨论 idea、提出假设或询问研究背景，无需先完成固定比较报告。\n\n' + '\n\n'.join(blocks))


def _sse(event: str, data: dict) -> str:
    """Encode one Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _retrieve_hits(
    session: Session, user_message: str, paper_ids: list[int] | None = None
) -> list[tuple[PaperChunk, float, Paper]]:
    """RAG retrieval: ranked ``(chunk, score, paper)`` triples for the question.

    Empty when no embedding model is configured or the query is blank.
    """
    from app.rag.index import retrieve

    if not (user_message or "").strip():
        return []
    hits: list[tuple[PaperChunk, float, Paper]] = []
    retrieved = retrieve(session, user_message, paper_ids=paper_ids) if paper_ids is not None else retrieve(session, user_message)
    for chunk, score in retrieved:
        hits.append((chunk, score, session.get(Paper, chunk.paper_id)))
    return hits


def _sources_from_hits(
    hits: list[tuple[PaperChunk, float, Paper]], limit: int = 5
) -> list[dict]:
    """Preserve each retrieved passage, including different locations in one paper."""
    from app.agent.source_passages import indexed_pages, paper_source
    sources: list[dict] = []
    seen = set()
    for chunk, _score, paper in hits:
        pid = chunk.paper_id
        key = (pid, chunk.ordinal, chunk.text)
        if key in seen or (paper is not None and paper.is_deleted):
            continue
        seen.add(key)
        title = (paper.title if paper else None) or f"#{pid}"
        pages = indexed_pages(chunk.text)
        sources.append(paper_source(pid, title, chunk.text,
                       'metadata' if chunk.ordinal == 0 and paper and (paper.title or paper.abstract) and not pages else 'full_text',
                       'initial_retrieval', pages))
        if len(sources) >= limit:
            break
    return sources


def _clip(text: str | None, limit: int) -> str:
    """Collapse whitespace and clip to ``limit`` characters (with ellipsis)."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 1, 0)] + "…"


def _paper_context(session: Session, paper_id: int, selected_text: str | None) -> str:
    """T5：就某篇论文提问时的聚焦上下文（同步/流式共用）。

    包含标题、元数据、AI 摘要、审阅矩阵、用户笔记与摘录、当前选中文本；
    每节与总长都受上限约束。论文不存在或已软删除时返回 404（调用方在
    持久化用户消息之前调用，保证失败请求不落库）。
    """
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        raise HTTPException(404, "paper not found")

    authors = ", ".join(parse_authors_json(paper.authors_json))
    meta = " / ".join(
        part
        for part in (
            authors,
            f"{paper.year}" if paper.year else "",
            paper.venue or "",
            paper.doi or "",
            f"arXiv:{paper.arxiv_id}" if paper.arxiv_id else "",
        )
        if part
    )
    sections: list[str] = [f"[论文上下文] {paper.title or f'#{paper.id}'}", f"当前论文工具标识：paper_id={paper.id}"]
    if meta:
        sections.append(f"元数据：{_clip(meta, _PAPER_CONTEXT_SECTION_MAX)}")

    summary_row = session.exec(
        select(Summary).where(Summary.paper_id == paper_id).order_by(Summary.created_at.desc())
    ).first()
    summary = parse_summary_json(summary_row.content_json) if summary_row else None
    if summary:
        summary_text = "；".join(f"{key}：{value}" for key, value in summary.items() if value)
        if summary_text:
            sections.append(f"AI 摘要：{_clip(summary_text, _PAPER_CONTEXT_SECTION_MAX)}")

    matrix = session.exec(
        select(ReviewMatrixEntry).where(ReviewMatrixEntry.paper_id == paper_id)
    ).first()
    if matrix:
        matrix_text = "；".join(
            f"{field}：{value}"
            for field in ("problem", "method", "dataset", "results", "limitations", "novelty")
            for value in [getattr(matrix, field, None)]
            if value
        )
        if matrix_text:
            sections.append(f"审阅矩阵：{_clip(matrix_text, _PAPER_CONTEXT_SECTION_MAX)}")

    notes = session.exec(
        select(PaperNote).where(PaperNote.paper_id == paper_id).order_by(PaperNote.updated_at.desc())
    ).all()
    if notes:
        note_text = "｜".join(f"[{note.kind}] {note.content}" for note in notes[:10])
        sections.append(f"用户笔记：{_clip(note_text, _PAPER_CONTEXT_SECTION_MAX)}")

    excerpts = session.exec(
        select(PaperExcerpt).where(PaperExcerpt.paper_id == paper_id).order_by(PaperExcerpt.created_at.desc())
    ).all()
    if excerpts:
        excerpt_text = "｜".join(
            f"（第 {excerpt.page} 页）{excerpt.quote}" if excerpt.page else excerpt.quote
            for excerpt in excerpts[:10]
        )
        sections.append(f"用户摘录：{_clip(excerpt_text, _PAPER_CONTEXT_SECTION_MAX)}")

    if selected_text and selected_text.strip():
        sections.append(f"当前选中文本：{_clip(selected_text, SELECTED_TEXT_MAX)}")

    block = "\n".join(sections)
    if len(block) > _PAPER_CONTEXT_TOTAL_MAX:
        block = block[: _PAPER_CONTEXT_TOTAL_MAX - 1] + "…"
    return block


def _standalone_selection_block(selected_text: str | None) -> str | None:
    """selected_text 单独出现（无 paper_id）时也保留给模型，不静默丢弃。"""
    if not selected_text or not selected_text.strip():
        return None
    return f"[用户选中文本]\n{_clip(selected_text, SELECTED_TEXT_MAX)}"


def _parse_sources(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [row for row in parsed if isinstance(row, dict)] if isinstance(parsed, list) else []


from app.skills.research_evidence import research_skill_prompt

CHAT_SYSTEM_PROMPT = (
    "所有对话入口具有相同的研究和行动能力；当前论文或论文集合只是初始背景，不限制可用工具。"
    "需要外部资料时可以 search_web 和 read_webpage，读取用户指定的本地文件可用 read_local_file；"
    "查找本地库之外的公开学术文献、核实书目信息或追溯某篇论文的相关工作时，可用 search_openalex 和 find_related_openalex，"
    "拿到开放获取 PDF 链接后用 import_paper_pdf 入库再精读，不要求用户手动下载。上传的文件和图片直接参考消息材料。"
    "用户要求保存灵感、记笔记或整理文档时，使用 save_research_idea、save_paper_note 或 save_document 当场执行，"
    "不要求切换页面或重复确认已明确的请求。只有目标、内容等关键要素不清楚时才澄清。保存完成后报告工具返回的位置或记录 ID，不能假称已保存。\n\n"
    "你是一名帮助研究者提高效率的科研助手。优先直接回答用户当前的问题，给出具体分析、可讨论的 idea 和可执行的实验建议。"
    "讨论假设、机制、选题和实验设计时可以基于通用知识推理，不要求先取得论文证据；"
    "自然地区分原文事实、分析推断和待验证假设。缺少证据不等于不能讨论，也不等于假设不成立。"
    "不要为了完美无缺而只罗列限制、拒绝分析或反复提示核查。\n\n"
    "需要确认用户论文库中的具体内容时，按需使用 search_library、get_paper、get_paper_full_text、list_concepts、find_related。"
    "用户想接着此前保存的文档或比较笔记研究时，可用 search_saved_documents 跨当前项目的对话查找成果，"
    "再用 read_saved_document 读取正文或其保存的原文来源；保留人工修订的事实与条件。"
    "用户问自己的笔记、摘录、批注、判断或审阅矩阵时优先 search_research_notes。"
    "查找论文里的实验、方法或解释时，可用 search_paper_text 按问题搜索正文，并用 paper_ids 聚焦相关论文；无需猜测原文的精确措辞。"
    "用户从专题研究继续讨论时，用 read_review 读取链接中 review 参数对应的已有分析和草稿；不要求用户重复粘贴，也不必等待整篇完成。"
    "用户关联论文整理成果时，用 read_research_task 按 task_id 和 version 读取其判断与保存来源，再围绕当前问题继续研究。"
    "已有材料足够就直接回答，不为普通讨论强制检索或精读全文。"
    "问题所需的具体事实确实缺失时，可用全文 query 或分页定位；不必为无关部分补齐全文。"
    "比较方法或判断可行性时，围绕影响当前决策的事实回读方法与实验设置，区分各模块的作用、训练过程与实际使用条件；"
    "可用全文工具 outline_only 查看章节目录，再用 section 读取具体步骤与实验设置；这比方法名首次命中的引言更适合判断能否使用。"
    "other_matches 是定位预览，可能省略数值的归属和条件；影响路线选择的结论应回到相应章节或完整表格上下文。先交付有用的分析，缺口按需补查，不要求所有字段齐全才输出。"
    "讨论实际复现或部署时，论文中存在训练步骤不等于用户必须重新训练；若这会改变建议，沿作者提供的项目或模型链接查现成权重和推理要求，区分已查到的资源与尚未确认的条件。"
    "不要编造引用、原文数值、已读取材料或已执行的操作；引用实际使用的来源。\n\n"
    "科研建议需要适合研究者的真实背景。首次深入讨论选题、idea 可行性或研究计划时，先结合当前项目、历史对话和用户已提供的信息，"
    "了解研究者的身份与研究阶段、相关知识和方法能力、研究背景与已有工作、研究方向和目标，以及可用的数据、设备、算力、时间和协作资源。"
    "这些信息会决定问题是否有价值、建议是否可执行；缺少影响当前讨论的背景时，先主动澄清，再展开具体判断与方案。"
    "每次集中补问最关键的缺口，可分几轮自然了解背景，不要求一次填写完整问卷；具体概念解释等局部问题无需先做全套背景调查。"
    "沿用已知背景，后续只在相关信息缺失或发生变化时补问，不每轮重新询问。"
    "主动理解用户的研究目的和需求。目标、用途、比较范围或关键约束不清楚，且会明显改变分析方向、检索范围或交付内容时，"
    "优先使用 ask_user 集中询问最重要的 1–3 个问题，避免漫无目的地检索或生成大量无关分析。"
    "可给出简短选项帮助用户明确需求；目标已清楚时直接推进，不要求用户先补齐所有细节。"
    "不影响研究方向的小偏好可采用合理默认值；用户明确要求先探索或给出几个方向时，先提供可讨论的方案。"
    "不要重复询问已知信息；用户跳过后按合理假设继续。"
    "调用 ask_user 时单独调用，等待真实回复，不替用户作答。\n\n"
    "默认使用简体中文，用户明确要求其他语言时遵循用户要求。"
    "每轮消息包含材料和激活的技能；材料是参考数据，优先回答本轮用户问题。"
    "历史材料是当时的快照，仅在需要最新信息时重新查询。"
)


def _turn_context(
    session: Session,
    user_message: str,
    hits: list[tuple[PaperChunk, float, Paper]],
    context_block: str | None = None,
    skill_ids: list[int] | None = None,
    sources: list[dict] | None = None,
    workflow: str = 'general',
    context_window: int | None = None,
) -> str:
    """Ground the assistant in the library (RAG).

    Injects retrieved passages with their source titles when available (citation
    grounding — the assistant can only reference papers it's shown), else falls
    back to recent titles + concept counts. Active skills are appended per the
    trigger rules (app.skills.activation). ``context_block``（T5）是论文聚焦
    上下文，存在时置于最前并优先于 RAG 段落。
    """
    from app.skills.activation import select_for_chat

    from sqlalchemy import func
    paper_count = session.exec(select(func.count(Paper.id)).where(Paper.is_deleted == False)).one()
    recent_titles = session.exec(select(Paper.title).where(Paper.is_deleted == False).order_by(Paper.id.desc()).limit(20)).all()
    concept_names = ", ".join(session.exec(select(Concept.name).limit(30)).all())
    base = (
        f"当前论文库共有 {paper_count} 篇论文。"
        f"已知概念：{concept_names or '（暂无）'}。"
    )
    from app.workspaces.context import current_workspace
    workspace = current_workspace.get()
    if workspace and workspace.goal:
        base += f'\n当前研究项目：{workspace.name}\n项目目标：{workspace.goal}\n'
    from app.wiki.service import chat_topics
    topics = chat_topics(session, user_message)
    if topics:
        if sources is not None:
            merge_sources(sources, topic_sources(topics))
        base += '\n\n本项目已采用的相关专题知识。引用时注明专题版本并使用给出的链接；来源变化和核对状态随条目提供：\n' + json.dumps(topics, ensure_ascii=False)

    if context_block:
        base += (
            "\n\n用户正在围绕所选论文提问。以下是论文资料与用户自己的研究沉淀，"
            "回答应优先基于这些材料：\n" + context_block
        )

    if hits:
        lines = []
        for chunk, _score, paper in hits:
            title = (paper.title if paper else None) or f"#{chunk.paper_id}"
            lines.append(f"[P{chunk.paper_id}] {title}\n{chunk.text}")
        base += "\n\nRelevant passages from your library:\n" + "\n\n".join(lines)
    elif not context_block or '[用户选择的论文讨论范围]' not in context_block:
        titles = "\n".join(f"- {title}" for title in recent_titles if title)
        if titles:
            base += f"\n\nRecent paper titles:\n{titles}"

    skills = select_for_chat(session, user_message, skill_ids)
    from app.skills.builtin import chat_prompt
    blocks = [f"[Active skill — {s.name}]\n{chat_prompt(s)}" for s in skills]
    if blocks:
        base += "\n\n" + "\n\n".join(blocks)
    from app.skills.workflows import writing_workflow
    workflow_block = writing_workflow(session, workflow, context_window)
    if workflow_block:
        base += '\n\n' + workflow_block
    return base


def _build_messages(
    session: Session,
    conversation: Conversation,
    user_message: str,
    hits: list[tuple[PaperChunk, float, Paper]],
    context_block: str | None = None,
    current_message_id: int | None = None,
    skill_ids: list[int] | None = None,
    context_window: int | None = None,
    response_tokens: int = 2048,
) -> list[dict]:
    """System prompt + the full conversation history (compaction trims later)."""
    history = session.exec(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)
    ).all()
    if current_message_id is not None:
        history = [m for m in history if m.id <= current_message_id or public_revision(m)]
    current = (next((m for m in history if m.id==current_message_id),None) if current_message_id is not None
               else next((m for m in reversed(history) if m.role == "user" and not public_revision(m)),None))
    new_context = current is not None and current.model_context is None
    if new_context:
        sources = _parse_sources(current.sources_json)
        request = json.loads(current.request_json or '{}')
        current.model_context = _turn_context(session, user_message, hits, context_block, skill_ids, sources,
                                             request.get('workflow', 'general'), context_window)
        current.sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        session.add(current)
        session.commit()
    review_requested = bool(json.loads(current.request_json or '{}').get('review_evidence')) if current else False
    system = CHAT_SYSTEM_PROMPT + ('\n\n' + research_skill_prompt() if review_requested else '')
    from app.skills.builtin import discovery_prompt
    skill_directory = discovery_prompt(session)
    if skill_directory:
        system += '\n\n' + skill_directory
    source_context = ''
    if current is not None:
        from app.agent.context import DEFAULT_CONTEXT_WINDOW, estimate_tokens, message_budget, total_tokens
        from app.agent.source_memory import carry_sources
        provided_texts = {}
        window = context_window or DEFAULT_CONTEXT_WINDOW
        if new_context:
            from app.agent.selected_materials import collect_selected_texts
            from app.agent.tools import tool_schemas
            request = json.loads(current.request_json or '{}')
            previous = next((m for m in reversed(history) if m.id < current.id), None)
            source_allowance = min(4000, window // 5) if previous and _parse_sources(previous.sources_json) else 0
            available = max(0, min(message_budget(window), window - response_tokens)
                            - estimate_tokens(json.dumps(tool_schemas(), ensure_ascii=False)) - source_allowance)
            original_context = current.model_context
            def fits(block):
                projection = _render_messages(history, system, current, '', current_message_id,
                                              original_context + '\n\n' + block)
                return total_tokens(projection) <= available
            block, provided_texts, supplied = collect_selected_texts(session, request, fits, current.id)
            if block:
                current.model_context = original_context + '\n\n' + block
                sources = _parse_sources(current.sources_json)
                merge_sources(sources, supplied)
                current.sources_json = json.dumps(sources, ensure_ascii=False)
                session.add(current); session.commit()
        state = json.loads(current.agent_state_json or '{}')
        if 'source_context' not in state:
            request = json.loads(current.request_json or '{}')
            allowed = request.get('paper_ids')
            if allowed is None and request.get('paper_id') is not None:
                allowed = [request['paper_id']]
            mandatory = total_tokens([{'role':'system', 'content':system},
                {'role':'user', 'content':attach_content((current.model_context or '') + current.content, request.get('attachments', []))}])
            budget = max(0, min(4000, window // 5, int(window * .75) - mandatory - 512))
            source_context, carried = carry_sources(session, conversation.id, current.id, allowed, budget,
                                                   provided_texts=provided_texts)
            state['source_context'] = source_context
            sources = _parse_sources(current.sources_json)
            merge_sources(sources, carried)
            current.sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
            current.agent_state_json = json.dumps(state, ensure_ascii=False)
            session.add(current); session.commit()
        else:
            source_context = state['source_context']
    return _render_messages(history, system, current, source_context, current_message_id)


def _render_messages(history, system, current, source_context, current_message_id, current_context=None):
    """Project stored turns without changing their material snapshots."""
    msgs: list[dict] = [{"role": "system", "content": system}]
    from app.agent.context_snapshots import coalesce_snapshots
    snapshots = coalesce_snapshots([(m.id, current_context if current and m.id == current.id and current_context is not None else m.model_context) for m in history
        if m.role == 'user' and m.model_context and not public_revision(m)])
    for m in history:
        content = m.content
        if m.role == 'assistant':
            msgs.extend(research_messages(content, json.loads(m.agent_state_json or '{}'), m.id))
            continue
        revision = public_revision(m)
        if revision:
            content = revision_context(m, revision)
        elif m.role == "user" and m.model_context:
            carried_context = ('\n\n' + source_context) if m.id == current.id and source_context else ''
            content = snapshots.get(m.id, m.model_context) + carried_context + "\n\n[本轮用户问题]\n" + content
        attachments = json.loads(m.request_json or "{}").get("attachments", []) if m.role == "user" else []
        msgs.append({"role": m.role, "content": attach_content(content, attachments)})
        if m.role == 'user' and m.id != current_message_id and m.delivery_status == 'failed':
            msgs.extend(research_messages('', json.loads(m.agent_state_json or '{}'), m.id))
    return msgs


def _context_window(session: Session, provider: Provider, model_id: str) -> int | None:
    """Look up the model's context window so the agent can budget against it."""
    from app.models import Model

    row = session.exec(
        select(Model).where(
            Model.provider_id == provider.id, Model.model_id == model_id
        )
    ).first()
    from app.providers.capabilities import known_context_window
    return (row.context_window if row else None) or known_context_window(provider,model_id)


def _max_iters(session: Session) -> int:
    """Agent tool-step budget from the `agent_max_iters` setting, clamped to a sane range."""
    from app.agent.loop import MAX_ITERS
    from app.models import Setting

    raw = session.get(Setting, "agent_max_iters")
    try:
        value = int(raw.value) if raw and raw.value else MAX_ITERS
    except (TypeError, ValueError):
        value = MAX_ITERS
    return max(4, min(200, value))


def _auto_title(text: str) -> str:
    """Derive a short conversation title from the first user message.

    Collapses whitespace and caps length so the sidebar stays readable. Returns
    "" for blank input (caller keeps the existing title in that case).
    """
    return " ".join((text or "").split())[:60]


@router.post("/chat/conversations")
def create_conversation(body: ConvCreate | None = None, session: Session = Depends(get_session)) -> dict:
    paper_id = body.paper_id if body else None
    if paper_id is not None:
        _paper_context(session, paper_id, None)
    ids = _validate_papers(session, body.paper_ids) if body and body.paper_ids is not None else []
    if ids and paper_id is not None:
        raise HTTPException(422, "请使用 paper_id 或 paper_ids 其中一种论文关联方式")
    c = Conversation(title=f"基于 {len(ids)} 篇论文讨论" if ids else "New conversation", paper_id=paper_id, paper_ids_json=json.dumps(ids))
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
    if "title" in body.model_fields_set:
        title = (body.title or "").strip()
        if not title:
            raise HTTPException(400, "title must not be empty")
        conv.title = title[:120]
    if "paper_id" in body.model_fields_set:
        if body.paper_id is not None:
            _paper_context(session, body.paper_id, None)
        conv.paper_id = body.paper_id
        conv.paper_ids_json = '[]'
    if "paper_ids" in body.model_fields_set:
        conv.paper_ids_json = json.dumps(_validate_papers(session, body.paper_ids or []))
        conv.paper_id = None
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
    msgs = session.exec(select(Message).where(Message.conversation_id == cid).order_by(Message.id)).all()
    last_turn=next((m for m in reversed(msgs) if not public_revision(m)),None)
    paper = session.get(Paper, conv.paper_id) if conv.paper_id else None
    return {
        "id": conv.id,
        "title": conv.title,
        "paper_id": paper.id if paper and not paper.is_deleted else None,
        "paper_title": paper.title if paper and not paper.is_deleted else None,
        "papers": [{"id": pid, "title": row.title if row else None, "unavailable": not row or row.is_deleted}
                   for pid in _conversation_papers(conv) for row in [session.get(Paper, pid)]],
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "document_revision": public_revision(m),
                "delivery_status": m.delivery_status,
                "error_message": m.error_message,
                "continuable": bool(m.role == "user" and m.agent_state_json and "evidence" in json.loads(m.agent_state_json)),
                "retryable": m.role == "user" and m == last_turn and m.delivery_status in {"pending", "failed"} and _turn_key(session, cid) not in _active_turns,
                "model": m.model,
                **public_sources(_parse_sources(m.sources_json)),
                "clarification": _clarification(m),
                "tools": json.loads(m.agent_state_json or "{}").get("tools", []),
                "updates": public_updates(json.loads(m.agent_state_json or '{}')),
                "attachments": json.loads(m.request_json or "{}").get("attachments", []),
            }
            for m in msgs
        ],
    }


def _clarification(message: Message) -> dict | None:
    if not message.clarification_json:
        return None
    return {**json.loads(message.clarification_json), "message_id": message.id}


def _resume_clarification(session: Session, conv: Conversation, body: MessageIn, question: Message):
    """Atomically consume a question and persist a retryable human answer."""
    request = _clarification(question)
    response = body.clarification_response
    if (response is None or question.role != "assistant" or question.id != response.message_id
            or request is None or request["status"] != "pending" or not question.agent_state_json):
        raise HTTPException(409, "该提问已处理或不属于当前对话，请刷新后继续。")
    try:
        body.content = answer_content(request, response)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    state = json.loads(question.agent_state_json)
    messages = [*state["messages"], {
        "role": "tool", "tool_call_id": state["tool_call_id"],
        "content": json.dumps({"user_response": response.model_dump(exclude={"message_id"}),
                               "content": body.content}, ensure_ascii=False),
    }]
    if body.attachments:
        messages.append({"role": "user", "content": attach_content("补充材料", [a.model_dump() for a in body.attachments])})
    state=resume_with_revisions(session,conv.id,question.id,{**state,'messages':messages})
    messages=state['messages']
    row = Message(conversation_id=conv.id, role="user", content=body.content,
                  delivery_status="pending", request_json=body.model_dump_json(),
                  agent_state_json=json.dumps({**{k: v for k, v in state.items() if k not in {'tools', 'updates'}}, "messages": messages}, ensure_ascii=False),
                  sources_json=question.sources_json)
    session.add(row)
    session.flush()
    request.update(status="skipped" if response.skipped else "answered",
                   response=response.model_dump(exclude={"message_id"}), response_message_id=row.id)
    question.clarification_json = json.dumps(request, ensure_ascii=False)
    conv.updated_at = utcnow()
    session.add(question)
    session.add(conv)
    session.commit()
    session.refresh(row)
    return row, messages, _parse_sources(row.sources_json)


def _prepare_turn(cid: int, body: MessageIn, session: Session):
    conv = session.get(Conversation, cid)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    session.info['chat_conversation_id'] = cid
    if not body.content.strip() and body.attachments:
        body.content = "请分析所附材料。"
    if not body.content.strip() and body.clarification_response is None:
        raise HTTPException(422, "问题不能为空。")
    ctx = pick_chat_model(session, body.model_config_id)
    if ctx is None:
        raise HTTPException(400, "no LLM provider configured")
    with _turn_lock:
        if _turn_key(session, cid) in _active_turns:
            raise HTTPException(409, "该对话仍在生成回答，请等待完成或停止后再试。")
        _active_turns.add(_turn_key(session, cid))
        _cancel_events[_turn_key(session, cid)] = Event()
    user_row = None
    persisted_id = None
    try:
        if body.retry_message_id is not None:
            user_row = latest_turn(session,cid)
            if (user_row is None or user_row.id != body.retry_message_id or user_row.role != "user"
                    or user_row.delivery_status not in {"pending", "failed"} or user_row.content != body.content):
                raise HTTPException(409, "只能重试当前对话最后一条未完成的问题，请刷新对话。")
            # Reuse the exact original request; UI selection may have changed since failure.
            requested_model = body.model_config_id
            body = MessageIn(**json.loads(user_row.request_json or json.dumps({"content": user_row.content})))
            if requested_model is not None:
                body.model_config_id = requested_model
                user_row.request_json = body.model_dump_json()
            ctx = pick_chat_model(session, body.model_config_id)
            validate_images(session, ctx, body.attachments)
            if json.loads(user_row.agent_state_json or '{}').get('messages'):
                state=resume_with_revisions(session,cid,user_row.id,json.loads(user_row.agent_state_json))
                user_row.agent_state_json=json.dumps(state,ensure_ascii=False)
                user_row.delivery_status = "pending"
                user_row.error_message = None
                session.add(user_row)
                session.commit()
                return conv, user_row, ctx, json.loads(user_row.agent_state_json)["messages"], _parse_sources(user_row.sources_json)
        else:
            last = latest_turn(session,cid)
            pending = _clarification(last) if last is not None else None
            if body.clarification_response is None and pending and pending["status"] == "pending":
                # The ordinary composer remains a valid free-text answer path.
                try:
                    body.clarification_response = ClarificationResponse(message_id=last.id, free_text=body.content)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
            if body.clarification_response is not None:
                if last is None:
                    raise HTTPException(409, "当前对话没有待回答的提问。")
                validate_images(session, ctx, body.attachments)
                row, messages, sources = _resume_clarification(session, conv, body, last)
                return conv, row, ctx, messages, sources
        validate_images(session, ctx, body.attachments)
        from app.skills.activation import select_for_chat
        try:
            select_for_chat(session, body.content, body.skill_ids)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        context_block = None
        if body.paper_ids is not None and body.paper_id is not None:
            raise HTTPException(422, "请使用 paper_id 或 paper_ids 其中一种论文关联方式")
        if body.paper_ids is None and "paper_id" not in body.model_fields_set:
            group = json.loads(conv.paper_ids_json or '[]')
            if group:
                body.paper_ids = group
        if body.paper_ids is not None:
            ids = list(dict.fromkeys(body.paper_ids))
            _validate_papers(session, [pid for pid in ids if pid not in _conversation_papers(conv)])
            body.paper_ids = ids
            conv.paper_ids_json = json.dumps(ids)
            conv.paper_id = None
            context_block = _group_context(session, ids) if ids else None
        elif "paper_id" not in body.model_fields_set:
            body.paper_id = conv.paper_id
        if body.paper_id is not None:
            context_block = _paper_context(session, body.paper_id, body.selected_text)
            conv.paper_id = body.paper_id
            conv.paper_ids_json = '[]'
        elif body.selected_text and context_block is None:
            context_block = _standalone_selection_block(body.selected_text)
        if user_row is None:
            first = session.exec(select(Message).where(Message.conversation_id == cid)).first() is None
            user_row = Message(conversation_id=cid, role="user", content=body.content,
                               request_json=body.model_dump_json())
            if first:
                conv.title = _auto_title(body.content) or conv.title
        user_row.delivery_status = "pending"
        user_row.error_message = None
        session.add(user_row)
        conv.updated_at = utcnow()
        session.add(conv)
        session.commit()
        session.refresh(user_row)
        persisted_id = user_row.id
        if user_row.model_context is None:
            # The agent sees the conversation and selected materials before
            # choosing a library query. A follow-up such as "how many runs?"
            # is not a standalone retrieval query. Search tools retain hybrid
            # retrieval and reranking when new evidence is actually needed.
            hits = []
            sources = _sources_from_hits(hits)
            user_row.sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
            session.add(user_row)
            session.commit()
        else:
            hits = []
            sources = _parse_sources(user_row.sources_json)
        from app.providers.output_budget import response_budget
        from app.agent.context import DEFAULT_CONTEXT_WINDOW
        window = _context_window(session, ctx[1], ctx[2])
        response_tokens = response_budget(window or DEFAULT_CONTEXT_WINDOW, 2048,
                                          ctx[0]._configured_effort(ctx[1], ctx[2]))
        messages = _build_messages(session, conv, body.content, hits, context_block, user_row.id, body.skill_ids,
                                   window, response_tokens)
        historical_images = [a for m in session.exec(select(Message).where(Message.conversation_id == cid)).all()
                             for a in json.loads(m.request_json or '{}').get('attachments', []) if a.get('kind') == 'image']
        if historical_images:
            validate_images(session, ctx, [Attachment(**a) for a in historical_images])
        return conv, user_row, ctx, messages, _parse_sources(user_row.sources_json)
    except Exception as exc:
        if persisted_id is not None:
            _fail_turn(session, persisted_id, str(exc))
        _release_turn(cid, session)
        raise


def _finish_turn(session: Session, user_row: Message, model_id: str, content: str, tokens: int, sources: list,
                 clarification: dict | None = None, agent_state: dict | None = None):
    user_row.delivery_status = "complete"
    user_row.error_message = None
    user_row.agent_state_json = None
    msg = Message(conversation_id=user_row.conversation_id, role="assistant", content=content,
                  model=model_id, tokens_used=tokens,
                  clarification_json=json.dumps(clarification, ensure_ascii=False) if clarification else None,
                  agent_state_json=json.dumps(agent_state, ensure_ascii=False) if agent_state else None,
                  sources_json=json.dumps(sources, ensure_ascii=False) if sources else None)
    session.add(user_row)
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


def _pause_turn(session: Session, user_row: Message, model_id: str, payload: dict, sources: list, title: str) -> dict:
    content = question_content(payload["request"])
    msg = _finish_turn(session, user_row, model_id, content, payload["tokens"], sources,
                       clarification=payload["request"], agent_state=payload["state"])
    return {"id": msg.id, "role": "assistant", "content": content, "model": model_id,
            "tokens": payload["tokens"], **public_sources(sources), "title": title, "clarification": _clarification(msg),
            'updates': public_updates(payload['state']), 'tools': payload['state'].get('tools', [])}


def _evidence_context(user_row: Message, sources: list) -> str | None:
    if not sources:
        return None
    # Give review the actual excerpts, not the JSON-encoded working catalog.
    # Catalog-only entries were not read and must not become evidence here.
    carried = '\n\n'.join(
        f"{source.get('url') if source.get('source_type') == 'web' else '[P' + str(source.get('paper_id')) + ']'} {source.get('title', '')} · {source.get('source_type', '')}\n"
        f"{source.get('locator') or source.get('retrieved_at', '')}\n{source.get('excerpt') or source.get('snippet') or ''}"
        for source in sources if source.get('carried_from_message')
    )
    return '\n\n'.join(part for part in (user_row.model_context, carried) if part) or None


def _plain_retrieval_fallback(session: Session, user_row: Message, sources: list):
    """Legacy grounding only after the provider explicitly rejects tool calls.

    Persist it with this turn so retry never spends a second retrieval request
    or silently substitutes newly changed paper text.
    """
    marker = '[工具不可用时的论文检索]'
    def retrieve():
        request = json.loads(user_row.request_json or '{}')
        if marker in (user_row.model_context or '') or any(
                a.get('saved_document') or a.get('research_task') for a in request.get('attachments', [])):
            return None
        ids = request.get('paper_ids')
        if ids is None and request.get('paper_id') is not None:
            ids = [request['paper_id']]
        supplied_ids = {s.get('paper_id') for s in sources if s.get('retrieved_by') == 'selected_full_text'
                        and s.get('provided_message_id') == user_row.id}
        if ids is not None:
            ids = [pid for pid in ids if pid not in supplied_ids]
            if not ids:
                return None
        try:
            hits = _retrieve_hits(session, user_row.content, ids) if ids is not None else _retrieve_hits(session, user_row.content)
            if ids is not None:
                hits = [hit for hit in hits if hit[0].paper_id in ids]
            extra = _sources_from_hits(hits)
            text = '\n\n'.join(f"[P{s['paper_id']}] {s['title']}\n{s.get('excerpt') or s['snippet']}" for s in extra)
            text = text or '此次检索未命中可用片段；仍可根据已有材料讨论。'
            merge_sources(sources, extra)
        except Exception:
            text = '此次论文检索未能完成；仍可根据已有材料讨论，不视为论文库中没有相关研究。'
        context = marker + '\n' + text
        user_row.model_context = (user_row.model_context or '') + '\n\n' + context
        user_row.sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        session.add(user_row); session.commit()
        return context
    return retrieve


@router.post("/chat/conversations/{cid}/messages")
def send_message(cid: int, body: MessageIn, session: Session = Depends(get_session)) -> dict:
    conv, user_row, (client, provider, model_id), messages, sources = _prepare_turn(cid, body, session)
    from app.agent.loop import run_agent
    try:
        content, tokens, audit = "", 0, None
        tools = json.loads(user_row.agent_state_json or "{}").get("tools", [])
        updates = public_updates(json.loads(user_row.agent_state_json or '{}'))
        for kind, payload in run_agent(client, provider, model_id, messages, session,
                context_window=_context_window(session, provider, model_id),
                review_evidence=bool(json.loads(user_row.request_json or "{}").get("review_evidence", False)),
                max_iters=_max_iters(session),
                cancelled=_cancel_events.get(_turn_key(session, cid)),
                continuation=json.loads(user_row.agent_state_json) if user_row.agent_state_json else None,
                evidence_context=_evidence_context(user_row, sources),
                on_tools_unavailable=_plain_retrieval_fallback(session, user_row, sources)):
            if kind == "ask_user":
                payload['state'].update(tools=tools, updates=updates)
                return _pause_turn(session, user_row, model_id, payload, sources, conv.title)
            elif kind == 'update':
                updates.append({'content': payload['content']})
                _save_progress(session, user_row, tools, updates, sources)
            elif kind == "tool":
                merge_sources(sources, payload.get('sources', []))
                tools.append({k: payload.get(k) for k in ("name", "args", "result", "ok")})
                _save_progress(session, user_row, tools, updates, sources)
            elif kind == "done":
                content, tokens = payload["content"], payload["tokens"]
                audit=payload.get('evidence_review')
            elif kind == "error":
                _fail_turn(session, user_row.id, payload["message"], ({**payload["state"], "sources": sources, "tools": tools, 'updates': updates} if payload.get("state") else None))
                raise HTTPException(500, payload["message"])
        msg = _finish_turn(session, user_row, model_id, content, tokens, sources,agent_state={'evidence_review':audit, 'tools':tools, 'updates': updates})
        return {"role": "assistant", "message_id": msg.id, "content": msg.content, "model": model_id,
                "tokens": tokens, **public_sources(sources), "title": conv.title, 'tools': tools, 'updates': updates}
    except Exception as exc:
        _fail_turn(session, user_row.id, str(exc))
        raise
    finally:
        _release_turn(cid, session)


@router.post("/chat/conversations/{cid}/messages/stream")
def stream_message(cid: int, body: MessageIn, session: Session = Depends(get_session)):
    """SSE accepted / tool / delta / done / ask_user / error with durable state."""
    conv, user_row, (client, provider, model_id), messages, sources = _prepare_turn(cid, body, session)
    title, user_id = conv.title, user_row.id

    def event_stream():
        from app.agent.loop import run_agent
        content, tokens, audit = "", 0, None
        tools = json.loads(user_row.agent_state_json or "{}").get("tools", [])
        updates = public_updates(json.loads(user_row.agent_state_json or '{}'))
        completed = False
        try:
            yield _sse("accepted", {"user_message_id": user_id, "content": user_row.content, "title": title,
                                    'tools': tools, 'updates': updates, **public_sources(sources),
                                    "clarification_response": body.clarification_response.model_dump() if body.clarification_response else None})
            for kind, payload in run_agent(client, provider, model_id, messages, session,
                    context_window=_context_window(session, provider, model_id),
                    review_evidence=bool(json.loads(user_row.request_json or "{}").get("review_evidence", False)),
                    max_iters=_max_iters(session),
                    cancelled=_cancel_events.get(_turn_key(session, cid)),
                    continuation=json.loads(user_row.agent_state_json) if user_row.agent_state_json else None,
                    evidence_context=_evidence_context(user_row, sources),
                    on_tools_unavailable=_plain_retrieval_fallback(session, user_row, sources)):
                if kind == "ask_user":
                    payload['state'].update(tools=tools, updates=updates)
                    result = _pause_turn(session, user_row, model_id, payload, sources, title)
                    completed = True
                    yield _sse("ask_user", result)
                    return
                elif kind == "status":
                    yield _sse("status", payload)
                elif kind == 'update':
                    updates.append({'content': payload['content']})
                    _save_progress(session, user_row, tools, updates, sources)
                    yield _sse('update', {'content': payload['content']})
                elif kind == "tool":
                    merge_sources(sources, payload.get('sources', []))
                    tools.append({k: payload.get(k) for k in ("name", "args", "result", "ok")})
                    _save_progress(session, user_row, tools, updates, sources)
                    yield _sse("tool", {**payload, **public_sources(sources)})
                elif kind == "delta":
                    content = payload["content"]
                    yield _sse("delta", {"content": content})
                elif kind == "done":
                    content, tokens = payload["content"], payload["tokens"]
                    audit=payload.get('evidence_review')
                elif kind == "error":
                    _fail_turn(session, user_id, payload["message"], ({**payload["state"], "sources": sources, "tools": tools, 'updates': updates} if payload.get("state") else None))
                    yield _sse("error", {**{k: v for k, v in payload.items() if k != "state"}, "user_message_id": user_id})
                    return
            saved = _finish_turn(session, user_row, model_id, content, tokens, sources,agent_state={'evidence_review':audit, 'tools':tools, 'updates': updates})
            completed = True
            yield _sse("done", {"message_id": saved.id, "content": content, "model": model_id, "tokens": tokens,
                                **public_sources(sources), "title": title})
        except Exception as exc:
            _fail_turn(session, user_id, str(exc))
            yield _sse("error", {"message": str(exc), "user_message_id": user_id})
        finally:
            try:
                if not completed:
                    _fail_turn(session, user_id, "回答未完成，可重试原问题。")
            finally:
                _release_turn(cid, session)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
