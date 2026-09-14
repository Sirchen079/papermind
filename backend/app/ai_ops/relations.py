"""Ingest-time AI relation analysis between a new paper and its neighbors (P9.2).

Asks the shared chat LLM to judge two relation kinds — ``method_conflict``
(method/result conflict) and ``combination`` (combinable directions) — between
a freshly ingested paper and its semantic/concept neighbors. Findings land as
Suggestion rows (dedup-keyed, idempotent). Every failure degrades silently:
no provider → skip, LLM error → skip, malformed JSON → skip.
"""

import json

from sqlmodel import Session, select

from app.models import Paper, Suggestion, Summary
from app.models.paper import parse_summary_json

_MAX_NEIGHBORS = 5

_RELATION_PROMPT = """你是一名科研文献分析专家。下面是「新论文」和若干「库内近邻论文」的信息。
请判断新论文与每篇近邻论文之间是否存在以下两类关系，只输出确实存在的关系：

- method_conflict：两者的方法或结论存在冲突 / 矛盾
- combination：两者的方法或方向可以结合，产生新的研究点

以 JSON 对象返回：{{"relations": [{{"related_paper_id": 近邻论文ID, "type": "method_conflict 或 combination", "reason": "一句话中文理由"}}]}}
若不存在任何关系，返回 {{"relations": []}}。仅返回 JSON 本身（不要解释文字，不要 markdown 代码块标记）。

新论文（ID {paper_id}）：
标题：{title}
摘要要点：{summary}

库内近邻论文：
{neighbors}"""


def _summary_text(session: Session, paper_id: int) -> str:
    row = session.exec(select(Summary).where(Summary.paper_id == paper_id)).first()
    if row is None or not row.content_json:
        return ""
    parsed = parse_summary_json(row.content_json)
    if not parsed:
        return ""
    return "；".join(f"{k}：{v}" for k, v in parsed.items() if isinstance(v, str) and v)


def _neighbor_ids(session: Session, paper: Paper) -> list[int]:
    """Top semantic neighbors via RAG, falling back to concept co-occurrence."""
    from app.rag.index import retrieve

    query = " ".join(part for part in (paper.title, paper.abstract) if part)
    seen: list[int] = []
    try:
        for chunk, _score in retrieve(session, query, k=_MAX_NEIGHBORS * 3):
            if chunk.paper_id != paper.id and chunk.paper_id not in seen:
                seen.append(chunk.paper_id)
                if len(seen) >= _MAX_NEIGHBORS:
                    return seen
    except Exception:  # noqa: BLE001 — retrieval is best-effort
        pass
    if seen:
        return seen

    # Concept co-occurrence fallback: neighbors sharing the most concepts.
    from app.knowledge.suggest import _shared_concepts

    shared = _shared_concepts(session, paper.id)
    ranked = sorted(shared.items(), key=lambda kv: -len(kv[1]))
    return [pid for pid, _concepts in ranked[:_MAX_NEIGHBORS]]


def _store_relations(session: Session, paper: Paper, relations: list[dict]) -> int:
    created = 0
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        related_id = rel.get("related_paper_id")
        kind = rel.get("type")
        reason = str(rel.get("reason") or "").strip()
        if not isinstance(related_id, int) or related_id == paper.id:
            continue
        if kind not in ("method_conflict", "combination"):
            continue
        neighbor = session.get(Paper, related_id)
        if neighbor is None or neighbor.is_deleted:
            continue
        a, b = sorted((paper.id, related_id))
        dedup_key = f"rel:{a}:{b}:{kind}"
        if (
            session.exec(
                select(Suggestion.id).where(Suggestion.dedup_key == dedup_key)
            ).first()
            is not None
        ):
            continue
        title = (
            f"“{paper.title or f'#{paper.id}'}”与“{neighbor.title or f'#{related_id}'}”"
            + ("存在方法/结论冲突" if kind == "method_conflict" else "存在可结合点")
        )
        session.add(
            Suggestion(
                kind=kind,
                title=title,
                detail_json=json.dumps(
                    {
                        "reason": reason,
                        "from_paper_id": paper.id,
                        "to_paper_id": related_id,
                    },
                    ensure_ascii=False,
                ),
                paper_id=a,
                related_paper_id=b,
                weight=1.0,
                dedup_key=dedup_key,
            )
        )
        created += 1
    if created:
        session.commit()
    return created


def analyze_relations(session: Session, paper: Paper) -> int:
    """Judge conflicts/combos between ``paper`` and its neighbors via the chat LLM.

    Returns the number of suggestions created. Silently returns 0 when no
    LLM is configured, no neighbors exist, or the model output is unusable.
    """
    from app.providers.selection import pick_llm

    ctx = pick_llm(session, "chat")
    if ctx is None:
        return 0
    client, provider, model_id = ctx

    summary = _summary_text(session, paper.id)
    if not summary and not paper.abstract:
        return 0

    neighbor_ids = _neighbor_ids(session, paper)
    if not neighbor_ids:
        return 0

    blocks = []
    for nid in neighbor_ids:
        neighbor = session.get(Paper, nid)
        if neighbor is None:
            continue
        neighbor_summary = _summary_text(session, nid)
        blocks.append(
            f"- ID {nid}：{(neighbor.title or '').strip()}\n  摘要要点：{neighbor_summary or neighbor.abstract or '（无）'}"
        )
    if not blocks:
        return 0

    prompt = _RELATION_PROMPT.format(
        paper_id=paper.id,
        title=(paper.title or "").strip() or "（无标题）",
        summary=summary or paper.abstract or "（无）",
        neighbors="\n".join(blocks),
    )
    try:
        result = client.complete(
            provider,
            model_id,
            [{"role": "user", "content": prompt}],
            request_kind="ingest",
        )
    except Exception:  # noqa: BLE001 — analysis must never break ingest
        return 0

    text = (result.content or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001 — malformed model output degrades silently
        return 0
    relations = parsed.get("relations") if isinstance(parsed, dict) else None
    if not isinstance(relations, list):
        return 0
    return _store_relations(session, paper, relations)
