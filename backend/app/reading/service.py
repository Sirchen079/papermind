import json
from collections.abc import Iterable

from sqlmodel import Session, select

from app.models import Concept, Paper, PaperConcept, PaperExcerpt, PaperNote, PaperReadingState, ReviewMatrixEntry, Summary
from app.models.base import utcnow
from app.models.paper import parse_authors_json, parse_summary_json
from app.providers.selection import pick_llm

STATUSES = {"unread", "queued", "reading", "read", "skipped"}
PRIORITIES = {"low", "normal", "high"}
NOTE_KINDS = {"note", "question", "idea", "critique", "todo"}
MATRIX_FIELDS = {
    "problem",
    "method",
    "dataset",
    "metrics",
    "results",
    "limitations",
    "novelty",
    "relation_to_thesis",
    "future_work",
    "notes",
}
UNCONFIGURED_LLM_ERROR = "未配置可用的 LLM，请先在设置中配置对话模型。"
MATRIX_FIELD_LABELS = {
    "problem": "研究问题",
    "method": "方法",
    "dataset": "数据集/研究对象",
    "metrics": "评价指标",
    "results": "主要结果",
    "limitations": "局限性",
    "novelty": "创新点",
    "relation_to_thesis": "与本人论文的关系",
    "future_work": "后续工作",
    "notes": "补充备注",
}

_MATRIX_SUGGEST_PROMPT = """你是面向中文研究生的文献审阅助手。请根据下面的论文信息，起草一份“审阅矩阵”。

要求：
1. 只返回 JSON 对象，不要 markdown，不要解释。
2. JSON 键必须限定为：{fields}
3. 每个值使用简洁中文，优先写可直接放进文献管理表格的短句。
4. 信息不足的字段请返回空字符串，不要编造论文没有提供的实验细节。
5. “与本人论文的关系”可以写成可复用角度，例如“可作为相关工作对比/方法背景/实验基线/局限性讨论”。

论文信息：
{context}
"""


def _paper(session: Session, paper_id: int) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        raise LookupError("paper not found")
    return paper


def _tags(value: object) -> str:
    if value is None:
        return "[]"
    if not isinstance(value, list):
        raise ValueError("tags must be a list")
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return json.dumps(cleaned, ensure_ascii=False)


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _score(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 1 or value > 5:
        raise ValueError(f"{field} must be an integer from 1 to 5")
    return value


def _state_row(session: Session, paper_id: int) -> PaperReadingState | None:
    return session.exec(select(PaperReadingState).where(PaperReadingState.paper_id == paper_id)).first()


def _default_state(paper_id: int) -> dict:
    return {
        "id": None,
        "paper_id": paper_id,
        "status": "unread",
        "priority": "normal",
        "rating": None,
        "relevance": None,
        "started_at": None,
        "finished_at": None,
        "last_read_at": None,
        "updated_at": None,
    }


def _dump(row: object | None) -> dict | None:
    if row is None:
        return None
    return row.model_dump(mode="json")  # type: ignore[attr-defined]


def _dump_state(row: PaperReadingState | None, paper_id: int) -> dict:
    if row is None:
        return _default_state(paper_id)
    return _dump(row) or _default_state(paper_id)


def _dump_note(row: PaperNote) -> dict:
    data = _dump(row) or {}
    data["tags"] = _parse_tags(row.tags_json)
    data.pop("tags_json", None)
    return data


def _dump_excerpt(row: PaperExcerpt) -> dict:
    data = _dump(row) or {}
    data["tags"] = _parse_tags(row.tags_json)
    data.pop("tags_json", None)
    return data


def _dump_matrix(row: ReviewMatrixEntry | None) -> dict | None:
    return _dump(row)


def _notes(session: Session, paper_id: int) -> list[PaperNote]:
    return session.exec(
        select(PaperNote).where(PaperNote.paper_id == paper_id).order_by(PaperNote.updated_at.desc())
    ).all()


def _excerpts(session: Session, paper_id: int) -> list[PaperExcerpt]:
    return session.exec(
        select(PaperExcerpt)
        .where(PaperExcerpt.paper_id == paper_id)
        .order_by(PaperExcerpt.page.is_(None), PaperExcerpt.page, PaperExcerpt.updated_at.desc())
    ).all()


def _matrix(session: Session, paper_id: int) -> ReviewMatrixEntry | None:
    return session.exec(select(ReviewMatrixEntry).where(ReviewMatrixEntry.paper_id == paper_id)).first()


def _latest_summary(session: Session, paper_id: int) -> dict | None:
    row = session.exec(
        select(Summary).where(Summary.paper_id == paper_id).order_by(Summary.created_at.desc())
    ).first()
    return parse_summary_json(row.content_json) if row else None


def _matrix_prompt_context(session: Session, paper: Paper) -> str:
    payload = {
        "metadata": {
            "title": paper.title,
            "authors": parse_authors_json(paper.authors_json),
            "year": paper.year,
            "venue": paper.venue,
            "doi": paper.doi,
            "arxiv_id": paper.arxiv_id,
        },
        "existing_summary": _latest_summary(session, paper.id),
        "abstract": paper.abstract or "",
        "full_text_excerpt": (paper.full_text or "")[:12000],
        "field_meanings": MATRIX_FIELD_LABELS,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _json_object_from_text(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1].strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _clean_matrix_draft(raw: dict | None) -> dict[str, str]:
    if raw is None:
        return {}
    draft: dict[str, str] = {}
    for field in MATRIX_FIELD_LABELS:
        value = raw.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            draft[field] = text
    return draft


def reading_summary(session: Session, paper_id: int) -> dict:
    state = _state_row(session, paper_id)
    out = _dump_state(state, paper_id)
    return {
        "status": out["status"],
        "priority": out["priority"],
        "rating": out["rating"],
        "relevance": out["relevance"],
    }


def get_reading_workspace(session: Session, paper_id: int) -> dict:
    _paper(session, paper_id)
    return {
        "state": _dump_state(_state_row(session, paper_id), paper_id),
        "matrix": _dump_matrix(_matrix(session, paper_id)),
        "notes": [_dump_note(row) for row in _notes(session, paper_id)],
        "excerpts": [_dump_excerpt(row) for row in _excerpts(session, paper_id)],
    }


def suggest_review_matrix(session: Session, paper_id: int) -> dict:
    paper = _paper(session, paper_id)
    picked = pick_llm(session, "chat")
    if picked is None:
        return {"configured": False, "model": None, "draft": {}, "error": UNCONFIGURED_LLM_ERROR}

    client, provider, model_id = picked
    prompt = _MATRIX_SUGGEST_PROMPT.format(
        fields=", ".join(MATRIX_FIELD_LABELS.keys()),
        context=_matrix_prompt_context(session, paper),
    )
    result = client.complete(
        provider,
        model_id,
        [{"role": "user", "content": prompt}],
        "reading_matrix_suggest",
        ref_id=f"paper:{paper_id}",
    )
    draft = _clean_matrix_draft(_json_object_from_text(result.content))
    error = None if draft else "模型没有返回可解析的审阅矩阵 JSON。"
    return {"configured": True, "model": model_id, "draft": draft, "error": error}


def patch_reading_state(session: Session, paper_id: int, payload: dict) -> dict:
    _paper(session, paper_id)
    row = _state_row(session, paper_id)
    if row is None:
        row = PaperReadingState(paper_id=paper_id)

    if "status" in payload:
        status = payload["status"]
        if status not in STATUSES:
            raise ValueError("invalid reading status")
        row.status = status
        now = utcnow()
        if status == "reading" and row.started_at is None:
            row.started_at = now
        if status == "read" and row.finished_at is None:
            row.finished_at = now
            if row.started_at is None:
                row.started_at = now
        if status in {"reading", "read"}:
            row.last_read_at = now

    if "priority" in payload:
        priority = payload["priority"]
        if priority not in PRIORITIES:
            raise ValueError("invalid reading priority")
        row.priority = priority

    if "rating" in payload:
        row.rating = _score(payload["rating"], "rating")
    if "relevance" in payload:
        row.relevance = _score(payload["relevance"], "relevance")

    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump_state(row, paper_id)


def create_note(session: Session, paper_id: int, payload: dict) -> dict:
    _paper(session, paper_id)
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ValueError("note content is required")
    kind = payload.get("kind", "note")
    if kind not in NOTE_KINDS:
        raise ValueError("invalid note kind")
    row = PaperNote(
        paper_id=paper_id,
        kind=kind,
        content=content,
        tags_json=_tags(payload.get("tags")),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump_note(row)


def _owned_note(session: Session, paper_id: int, note_id: int) -> PaperNote:
    row = session.get(PaperNote, note_id)
    if row is None or row.paper_id != paper_id:
        raise LookupError("note not found")
    _paper(session, paper_id)
    return row


def patch_note(session: Session, paper_id: int, note_id: int, payload: dict) -> dict:
    row = _owned_note(session, paper_id, note_id)
    if "kind" in payload:
        if payload["kind"] not in NOTE_KINDS:
            raise ValueError("invalid note kind")
        row.kind = payload["kind"]
    if "content" in payload:
        content = str(payload["content"] or "").strip()
        if not content:
            raise ValueError("note content is required")
        row.content = content
    if "tags" in payload:
        row.tags_json = _tags(payload["tags"])
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump_note(row)


def delete_note(session: Session, paper_id: int, note_id: int) -> None:
    row = _owned_note(session, paper_id, note_id)
    session.delete(row)
    session.commit()


def create_excerpt(session: Session, paper_id: int, payload: dict) -> dict:
    _paper(session, paper_id)
    quote = str(payload.get("quote") or "").strip()
    if not quote:
        raise ValueError("excerpt quote is required")
    page = payload.get("page")
    if page is not None and (not isinstance(page, int) or page <= 0):
        raise ValueError("page must be a positive integer")
    row = PaperExcerpt(
        paper_id=paper_id,
        quote=quote,
        page=page,
        section=payload.get("section"),
        locator=payload.get("locator"),
        note=payload.get("note"),
        tags_json=_tags(payload.get("tags")),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump_excerpt(row)


def _owned_excerpt(session: Session, paper_id: int, excerpt_id: int) -> PaperExcerpt:
    row = session.get(PaperExcerpt, excerpt_id)
    if row is None or row.paper_id != paper_id:
        raise LookupError("excerpt not found")
    _paper(session, paper_id)
    return row


def patch_excerpt(session: Session, paper_id: int, excerpt_id: int, payload: dict) -> dict:
    row = _owned_excerpt(session, paper_id, excerpt_id)
    if "quote" in payload:
        quote = str(payload["quote"] or "").strip()
        if not quote:
            raise ValueError("excerpt quote is required")
        row.quote = quote
    if "page" in payload:
        page = payload["page"]
        if page is not None and (not isinstance(page, int) or page <= 0):
            raise ValueError("page must be a positive integer")
        row.page = page
    for field in ("section", "locator", "note"):
        if field in payload:
            setattr(row, field, payload[field])
    if "tags" in payload:
        row.tags_json = _tags(payload["tags"])
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump_excerpt(row)


def delete_excerpt(session: Session, paper_id: int, excerpt_id: int) -> None:
    row = _owned_excerpt(session, paper_id, excerpt_id)
    session.delete(row)
    session.commit()


def upsert_review_matrix(session: Session, paper_id: int, payload: dict) -> dict:
    _paper(session, paper_id)
    row = _matrix(session, paper_id)
    if row is None:
        row = ReviewMatrixEntry(paper_id=paper_id)
    for field in MATRIX_FIELDS:
        if field in payload:
            value = payload[field]
            setattr(row, field, str(value).strip() if value is not None else None)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump_matrix(row) or {}


def _contains_any(values: Iterable[str | None], query: str) -> bool:
    hay = " ".join(value or "" for value in values).lower()
    return query.lower() in hay


def _concept_search_index(session: Session) -> dict[int, list[str | None]]:
    rows = session.exec(select(PaperConcept, Concept).join(Concept, PaperConcept.concept_id == Concept.id)).all()
    index: dict[int, list[str | None]] = {}
    for link, concept in rows:
        index.setdefault(link.paper_id, []).extend([concept.name, concept.type, concept.description, link.evidence])
    return index


def list_review_matrix(
    session: Session,
    *,
    status: str | None = None,
    q: str | None = None,
    min_relevance: int | None = None,
    high_priority: bool = False,
) -> list[dict]:
    if status is not None and status not in STATUSES:
        raise ValueError("invalid reading status")
    if min_relevance is not None:
        _score(min_relevance, "min_relevance")

    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    concept_search = _concept_search_index(session) if q else {}
    rows = []
    for paper in papers:
        state = _dump_state(_state_row(session, paper.id), paper.id)
        matrix = _dump_matrix(_matrix(session, paper.id))
        if status and state["status"] != status:
            continue
        if high_priority and state["priority"] != "high":
            continue
        if min_relevance is not None and (state["relevance"] or 0) < min_relevance:
            continue
        search_values = [paper.title, paper.authors_json, *concept_search.get(paper.id, [])]
        if matrix:
            search_values.extend(str(matrix.get(field) or "") for field in MATRIX_FIELDS)
        if q and not _contains_any(search_values, q):
            continue
        rows.append(
            {
                "paper": {
                    "id": paper.id,
                    "title": paper.title,
                    "authors": parse_authors_json(paper.authors_json),
                    "year": paper.year,
                    "venue": paper.venue,
                },
                "state": {
                    "status": state["status"],
                    "priority": state["priority"],
                    "rating": state["rating"],
                    "relevance": state["relevance"],
                },
                "matrix": matrix,
            }
        )
    return rows
