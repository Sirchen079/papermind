"""Claim-Evidence 图谱的抽取与论断关系分析（P12.2 / P12.3）。

抽取是**可选开关**（Setting ``claim_extraction_enabled``，默认关，控成本）：
开启时入库后用共享 chat 模型抽 1–3 条中文主论断（``source="ai"``）。
``analyze_claim_relations`` 是 P9.2 ``analyze_relations`` 在论断层面的扩展：
把新论文与其近邻论文的论断交给模型判断 supports/contradicts/extends，
产出 ClaimRelation（唯一键幂等）与 ``claim_relation`` 建议（可一键转 Idea）。
所有 LLM 失败一律静默降级，绝不阻塞入库。
"""

import json

from sqlmodel import Session, select

from app.models import Claim, ClaimRelation, Paper, Setting, Suggestion, Summary
from app.models.claim import CLAIM_KINDS, CLAIM_RELATION_TYPES
from app.models.paper import parse_summary_json

_SETTING_KEY = "claim_extraction_enabled"
_MAX_NEIGHBORS = 5  # 与论文级关系分析（P9.2）一致的近邻广度
_MAX_AI_CLAIMS = 3
_RELATION_WEIGHTS = {"contradicts": 1.5, "supports": 1.0, "extends": 1.0}
_TYPE_LABELS = {"contradicts": "相互矛盾", "supports": "相互支持", "extends": "互为延伸"}

_EXTRACT_PROMPT = """你是科研文献分析专家。请从下面这篇论文中提炼 1–3 条**主要论断**（claim）。

要求：
1. 论断是论文断言成立的具体陈述（方法有效/结论/发现），不是主题词。
2. 每条一句话，简洁中文，尽量保留可被反驳的具体内容（数字、条件、对象）。
3. 只返回 JSON 对象：{{"claims": ["论断1", "论断2"]}}，不要解释，不要 markdown 标记。

论文信息：
{context}
"""

_RELATION_PROMPT = """你是科研文献分析专家。下面是「新论文」和若干「库内近邻论文」的论断（claim）列表。
请判断不同论文的论断之间是否存在以下关系，只输出确实存在的关系：

- supports：一条论断为另一条提供支持/佐证
- contradicts：两条论断相互矛盾/冲突
- extends：一条论断在另一条基础上延伸/推广

以 JSON 对象返回：{{"relations": [{{"claim_a_id": 论断ID, "claim_b_id": 论断ID, "type": "supports 或 contradicts 或 extends", "reason": "一句话中文理由"}}]}}
若不存在任何关系，返回 {{"relations": []}}。仅返回 JSON 本身。

新论文（ID {paper_id}）：{title}
{new_claims}

近邻论文论断：
{neighbor_claims}"""


def claim_extraction_enabled(session: Session) -> bool:
    row = session.get(Setting, _SETTING_KEY)
    return bool(row and (row.value or "").strip().lower() in {"1", "true", "yes", "on"})


def _normalize_claim_text(text: str) -> str:
    """去全部空白 + 小写——中文为主的论断幂等比较。"""
    return "".join((text or "").split()).lower()


def _paper(session: Session, paper_id: int) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        raise LookupError("paper not found")
    return paper


def _live_claims(session: Session, paper_id: int) -> list[Claim]:
    return session.exec(
        select(Claim).where(
            Claim.paper_id == paper_id,
            Claim.is_deleted == False,  # noqa: E712
        )
    ).all()


def _summary_text(session: Session, paper: Paper) -> str:
    row = session.exec(select(Summary).where(Summary.paper_id == paper.id)).first()
    parsed = parse_summary_json(row.content_json) if row and row.content_json else None
    if parsed:
        return "；".join(f"{k}：{v}" for k, v in parsed.items() if isinstance(v, str) and v)
    return paper.abstract or ""


def _json_object(text: str) -> dict | None:
    content = (text or "").strip()
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) >= 3:
            content = parts[1].strip()
            if content.lower().startswith("json"):
                content = content[4:].strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _dump_claim(row: Claim) -> dict:
    return {
        "id": row.id,
        "paper_id": row.paper_id,
        "text": row.text,
        "kind": row.kind,
        "source": row.source,
        "excerpt_id": row.excerpt_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_claims(session: Session, paper_id: int) -> list[dict]:
    _paper(session, paper_id)
    return [_dump_claim(row) for row in _live_claims(session, paper_id)]


def create_claim(session: Session, paper_id: int, payload: dict) -> dict:
    paper = _paper(session, paper_id)
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("claim text is required")
    kind = payload.get("kind", "main")
    if kind not in CLAIM_KINDS:
        raise ValueError("invalid claim kind")
    excerpt_id = payload.get("excerpt_id")
    if excerpt_id is not None:
        from app.models import PaperExcerpt

        excerpt = session.get(PaperExcerpt, excerpt_id)
        if excerpt is None or excerpt.paper_id != paper_id:
            raise ValueError("excerpt does not belong to this paper")
    row = Claim(paper_id=paper.id, text=text, kind=kind, source="user", excerpt_id=excerpt_id)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _dump_claim(row)


def delete_claim(session: Session, claim_id: int) -> None:
    row = session.get(Claim, claim_id)
    if row is None or row.is_deleted:
        raise LookupError("claim not found")
    row.is_deleted = True
    session.add(row)
    session.commit()


def extract_claims(session: Session, paper: Paper) -> int:
    """Opt-in ingest-time extraction of 1–3 main claims. Returns created count.

    Idempotent per paper: a claim whose normalized text already exists on the
    paper (ai or user) is skipped. Any failure returns 0 without raising.
    """
    if not claim_extraction_enabled(session):
        return 0
    from app.providers.selection import pick_llm

    picked = pick_llm(session, "chat")
    if picked is None:
        return 0
    client, provider, model_id = picked

    context = json.dumps(
        {
            "title": paper.title or "",
            "summary": _summary_text(session, paper),
            "abstract": paper.abstract or "",
        },
        ensure_ascii=False,
    )
    try:
        result = client.complete(
            provider,
            model_id,
            [{"role": "user", "content": _EXTRACT_PROMPT.format(context=context)}],
            request_kind="ingest",
        )
    except Exception:  # noqa: BLE001 — extraction must never break ingest
        return 0

    parsed = _json_object(result.content)
    raw_claims = parsed.get("claims") if parsed else None
    if not isinstance(raw_claims, list):
        return 0

    existing = {
        _normalize_claim_text(row.text) for row in _live_claims(session, paper.id)
    }
    created = 0
    for item in raw_claims:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        normalized = _normalize_claim_text(text)
        if not normalized or normalized in existing:
            continue
        existing.add(normalized)
        session.add(Claim(paper_id=paper.id, text=text, kind="main", source="ai"))
        created += 1
        if created >= _MAX_AI_CLAIMS:
            break
    if created:
        session.commit()
    return created


def _neighbor_ids(session: Session, paper: Paper) -> list[int]:
    """Reuse the P9.2 neighbor strategy (RAG semantic, concept co-occurrence fallback)."""
    from app.ai_ops.relations import _neighbor_ids as relations_neighbor_ids

    return relations_neighbor_ids(session, paper)


def analyze_claim_relations(session: Session, paper: Paper) -> int:
    """Judge claim-level relations between ``paper`` and its neighbors.

    Stores ClaimRelation rows (unique-key idempotent) plus one
    ``claim_relation`` Suggestion per relation so the existing 「转为 Idea」
    flow applies. Returns the number of relations created; silently 0 on any
    failure or when either side has no claims.
    """
    from app.providers.selection import pick_llm

    new_claims = _live_claims(session, paper.id)
    if not new_claims:
        return 0
    picked = pick_llm(session, "chat")
    if picked is None:
        return 0
    client, provider, model_id = picked

    neighbor_ids = _neighbor_ids(session, paper)
    neighbor_claims: dict[int, Claim] = {}
    claim_titles: dict[int, str] = {}
    for nid in neighbor_ids:
        neighbor = session.get(Paper, nid)
        if neighbor is None or neighbor.is_deleted:
            continue
        title = (neighbor.title or f"#{nid}").strip()
        for row in _live_claims(session, nid):
            neighbor_claims[row.id] = row
            claim_titles[row.id] = title
    if not neighbor_claims:
        return 0

    new_paper_title = (paper.title or f"#{paper.id}").strip()
    for claim in new_claims:
        claim_titles[claim.id] = new_paper_title
    known_ids = set(claim_titles)

    def _line(claim: Claim) -> str:
        return f"- ID {claim.id}（论文「{claim_titles[claim.id]}」）：{claim.text}"

    prompt = _RELATION_PROMPT.format(
        paper_id=paper.id,
        title=new_paper_title,
        new_claims="\n".join(_line(c) for c in new_claims) or "（无论断）",
        neighbor_claims="\n".join(_line(c) for c in neighbor_claims.values()),
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

    parsed = _json_object(result.content)
    relations = parsed.get("relations") if parsed else None
    if not isinstance(relations, list):
        return 0

    created = 0
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        a_id, b_id = rel.get("claim_a_id"), rel.get("claim_b_id")
        rel_type = rel.get("type")
        reason = str(rel.get("reason") or "").strip()
        if not isinstance(a_id, int) or not isinstance(b_id, int):
            continue
        if a_id not in known_ids or b_id not in known_ids or a_id == b_id:
            continue
        if rel_type not in CLAIM_RELATION_TYPES:
            continue
        claim_a, claim_b = session.get(Claim, a_id), session.get(Claim, b_id)
        if claim_a is None or claim_b is None or claim_a.paper_id == claim_b.paper_id:
            continue
        # 只保留「新论文 ↔ 近邻」跨论文关系，且规范序 a < b。
        lo, hi = sorted((claim_a, claim_b), key=lambda c: c.id)
        if not session.exec(
            select(ClaimRelation.id).where(
                ClaimRelation.claim_a_id == lo.id,
                ClaimRelation.claim_b_id == hi.id,
                ClaimRelation.type == rel_type,
            )
        ).first():
            session.add(
                ClaimRelation(
                    claim_a_id=lo.id,
                    claim_b_id=hi.id,
                    type=rel_type,
                    source="ai",
                    note=reason or None,
                )
            )
        else:
            continue  # 关系已存在：幂等，不再重复出建议
        first, second = sorted((lo.paper_id, hi.paper_id))
        title = f"「{claim_titles[lo.id]}」与「{claim_titles[hi.id]}」的论断{_TYPE_LABELS[rel_type]}"
        dedup_key = f"claim_rel:{lo.id}:{hi.id}:{rel_type}"
        if (
            session.exec(select(Suggestion.id).where(Suggestion.dedup_key == dedup_key)).first()
            is None
        ):
            session.add(
                Suggestion(
                    kind="claim_relation",
                    title=title,
                    detail_json=json.dumps(
                        {
                            "type": rel_type,
                            "reason": reason,
                            "claim_a_id": lo.id,
                            "claim_b_id": hi.id,
                            "claim_a_text": lo.text,
                            "claim_b_text": hi.text,
                            "from_paper_id": lo.paper_id,
                            "to_paper_id": hi.paper_id,
                        },
                        ensure_ascii=False,
                    ),
                    paper_id=first,
                    related_paper_id=second,
                    weight=_RELATION_WEIGHTS[rel_type],
                    dedup_key=dedup_key,
                )
            )
        created += 1
    if created:
        session.commit()
    return created
