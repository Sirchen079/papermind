"""Chapter draft generation (P10.5).

Collects the chapter's linked papers (PaperLink) grouped by role, each with
its AI summary and review-matrix row, and asks the shared chat LLM for a
Chinese related-work style markdown draft. Citations use ``[@citation_key]``
placeholders whose keys match the .bib export (P10.6). Every generation
appends a ChapterDraft row — append-only version history.
"""

from sqlmodel import Session, select

from app.archive.bibtex import citekey
from app.models import Chapter, ChapterDraft, Paper, PaperLink, ReviewMatrixEntry, Summary
from app.models.paper import parse_summary_json
from app.thesis.service import ROLE_LABELS

# Display order for the role groups in the prompt.
_ROLE_ORDER = [
    "background",
    "method",
    "comparison",
    "evidence",
    "limitation",
    "inspiration",
    "related",
    "to_read",
]

_MATRIX_FIELDS = ["problem", "method", "results", "limitations", "novelty"]
_MATRIX_LABELS = {
    "problem": "问题",
    "method": "方法",
    "results": "结果",
    "limitations": "局限",
    "novelty": "创新点",
}

_DRAFT_PROMPT = """你是一名学术写作者。请根据下面的「章节信息」和「已挂载论文」，用简体中文写一段 related-work 综述风格的 markdown 草稿。

要求：
- 围绕章节标题与提纲组织行文，把各角色的论文自然融入论述（不要逐篇列表罗列）；
- 每篇论文都必须在合适的位置以 [@citation_key] 占位引用，key 必须与论文列表给出的完全一致，一字不改；
- 只概括提供的信息（摘要要点/矩阵），不要编造论文里没有的内容；
- 直接输出 markdown 正文本身：不要任何解释文字，不要 markdown 代码块标记。

章节标题：{title}
章节提纲：{outline}

已挂载论文：
{papers}"""


class DraftGenerationError(RuntimeError):
    """The LLM call failed or returned nothing usable (API maps to 502)."""


_SUMMARY_LABELS = {
    "problem": "问题",
    "method": "方法",
    "dataset": "数据集",
    "metrics": "指标",
    "results": "结果",
    "limitations": "局限",
    "novelty": "创新点",
    "relation_to_thesis": "与论文关系",
    "future_work": "未来工作",
    "notes": "备注",
    "freeform": "摘要",
}


def _summary_text(session: Session, paper_id: int) -> str:
    row = session.exec(select(Summary).where(Summary.paper_id == paper_id)).first()
    if row is None or not row.content_json:
        return ""
    parsed = parse_summary_json(row.content_json)
    if not parsed:
        return ""
    parts = []
    for key, value in parsed.items():
        if not (isinstance(value, str) and value.strip()):
            continue
        label = _SUMMARY_LABELS.get(key, key)
        parts.append(f"{label}：{value.strip()}")
    return "；".join(parts)


def _matrix_text(session: Session, paper_id: int) -> str:
    row = session.exec(
        select(ReviewMatrixEntry).where(ReviewMatrixEntry.paper_id == paper_id)
    ).first()
    if row is None:
        return ""
    parts = []
    for field in _MATRIX_FIELDS:
        value = str(getattr(row, field) or "").strip()
        if value:
            parts.append(f"{_MATRIX_LABELS[field]}：{value}")
    return "；".join(parts)


def _paper_blocks(session: Session, chapter_id: int) -> list[str]:
    """One prompt block per linked paper, ordered by role group."""
    links = session.exec(select(PaperLink).where(PaperLink.chapter_id == chapter_id)).all()
    grouped: dict[str, list[PaperLink]] = {}
    for link in links:
        grouped.setdefault(link.role, []).append(link)
    blocks: list[str] = []
    for role in sorted(grouped, key=lambda r: (_ROLE_ORDER.index(r) if r in _ROLE_ORDER else 99, r)):
        for link in grouped[role]:
            paper = session.get(Paper, link.paper_id)
            if paper is None or paper.is_deleted:
                continue
            role_label = ROLE_LABELS.get(link.role, link.role)
            key = citekey(paper)
            title = (paper.title or f"#{paper.id}").strip()
            parts = [f"- [角色：{role_label}] citation_key={key} 标题：{title}"]
            summary = _summary_text(session, paper.id) or (paper.abstract or "").strip()
            if summary:
                parts.append(f"  摘要要点：{summary[:1200]}")
            matrix = _matrix_text(session, paper.id)
            if matrix:
                parts.append(f"  矩阵：{matrix[:800]}")
            if link.note:
                parts.append(f"  挂载说明：{link.note.strip()}")
            blocks.append("\n".join(parts))
    return blocks


def _strip_outer_fence(text: str) -> str:
    """Drop one wrapping ```… fence if the model added one."""
    text = (text or "").strip()
    if text.startswith("```") and text.count("```") >= 2:
        inner = text.split("```", 2)[1]
        if inner.lstrip().lower().startswith("markdown"):
            inner = inner.lstrip()[8:]
        text = inner.strip()
    return text


def _dump(row) -> dict:
    return {
        "id": row.id,
        "chapter_id": row.chapter_id,
        "content": row.content,
        "model": row.model,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def generate_draft(session: Session, chapter_id: int) -> dict:
    """Generate a draft for the chapter and store it as a new version.

    Raises LookupError (chapter missing), ValueError (no linked papers /
    no LLM configured — API → 400) or DraftGenerationError (LLM failed —
    API → 502).
    """
    from app.providers.selection import pick_llm

    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise LookupError("chapter not found")

    blocks = _paper_blocks(session, chapter_id)
    if not blocks:
        raise ValueError("该章节尚未挂载任何论文，请先在论文详情中把论文挂载到该章节")

    ctx = pick_llm(session, "chat")
    if ctx is None:
        raise ValueError("未配置 LLM 提供商，无法生成草稿")
    client, provider, model_id = ctx

    prompt = _DRAFT_PROMPT.format(
        title=chapter.title,
        outline=(chapter.outline or "").strip() or "（无提纲）",
        papers="\n".join(blocks),
    )
    try:
        result = client.complete(
            provider,
            model_id,
            [{"role": "user", "content": prompt}],
            request_kind="ingest",
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as 502 with reason
        raise DraftGenerationError(f"{type(exc).__name__}: {exc}") from exc
    content = _strip_outer_fence(result.content or "")
    if not content:
        raise DraftGenerationError("模型返回了空内容，请重试或更换模型")

    draft = ChapterDraft(chapter_id=chapter_id, content=content, model=model_id)
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return _dump(draft)


def list_drafts(session: Session, chapter_id: int) -> list[dict]:
    """Version history for the chapter, newest first."""
    rows = session.exec(
        select(ChapterDraft)
        .where(ChapterDraft.chapter_id == chapter_id)
        .order_by(ChapterDraft.created_at.desc(), ChapterDraft.id.desc())
    ).all()
    return [_dump(row) for row in rows]
