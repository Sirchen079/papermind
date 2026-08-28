"""Research tools the agent can call.

Most tools are read-only queries over the local library. A small set performs
explicit organization actions, such as adding tags or placing a paper into a
collection. Each tool returns a JSON string so the model gets structured,
predictable data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from sqlmodel import Session, select

from app.models import Concept, Paper, PaperConcept, Summary
from app.models.paper import parse_authors_json, parse_summary_json
from app.organization.service import (
    add_paper_to_collection,
    attach_tag_to_paper,
    create_or_update_collection,
    create_or_update_tag,
)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[Session, dict[str, Any]], str]

    def schema(self) -> dict[str, Any]:
        """OpenAI function-calling schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _authors(p: Paper) -> list[str]:
    return parse_authors_json(p.authors_json)[:3]


def _brief(p: Paper) -> dict[str, Any]:
    return {"id": p.id, "title": p.title, "year": p.year, "authors": _authors(p)}


def _active_paper_ids(session: Session) -> set[int]:
    return {
        int(pid)
        for pid in session.exec(select(Paper.id).where(Paper.is_deleted == False)).all()  # noqa: E712
        if pid is not None
    }


def _concept_names(session: Session, paper_id: int) -> list[str]:
    cids = {
        row.concept_id
        for row in session.exec(
            select(PaperConcept).where(PaperConcept.paper_id == paper_id)
        ).all()
    }
    if not cids:
        return []
    return [
        c.name
        for c in session.exec(select(Concept).where(Concept.id.in_(cids))).all()
    ]


def _summary(session: Session, paper_id: int) -> dict[str, Any] | None:
    row = session.exec(
        select(Summary).where(Summary.paper_id == paper_id)
    ).first()
    if row is None or not row.content_json:
        return None
    return parse_summary_json(row.content_json)


def t_search_library(session: Session, query: str, top_k: int = 5) -> str:
    """Keyword search over the library (title + abstract + extracted concepts)."""
    qwords = {w.lower() for w in (query or "").split() if len(w) > 2}
    papers = session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
    # concept names per paper (one pass)
    names_by_paper: dict[int, set[str]] = {}
    if qwords:
        active_ids = {p.id for p in papers if p.id is not None}
        links = session.exec(select(PaperConcept)).all()
        links = [link for link in links if link.paper_id in active_ids]
        cids = {lc.concept_id for lc in links}
        cname = {c.id: (c.name or "").lower() for c in session.exec(select(Concept).where(Concept.id.in_(cids))).all()}
        for lc in links:
            names_by_paper.setdefault(lc.paper_id, set()).add(cname.get(lc.concept_id, ""))

    scored: list[tuple[int, Paper]] = []
    for p in papers:
        text = f"{p.title or ''} {p.abstract or ''}".lower()
        score = sum(1 for w in qwords if w in text)
        score += sum(1 for w in qwords if w in names_by_paper.get(p.id, set()))
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], -(x[1].year or 0)))
    out = [
        {**_brief(p), "score": s, "abstract": (p.abstract or "")[:160]}
        for s, p in scored[: top_k]
    ]
    return json.dumps(out or [{"note": "no matching papers"}], ensure_ascii=False)


def t_get_paper(session: Session, paper_id: int) -> str:
    """Full metadata + AI summary + concepts for one paper."""
    p = session.get(Paper, paper_id)
    if p is None or p.is_deleted:
        return json.dumps({"error": f"paper {paper_id} not found"})
    return json.dumps(
        {
            **_brief(p),
            "abstract": p.abstract,
            "venue": p.venue,
            "doi": p.doi,
            "arxiv_id": p.arxiv_id,
            "concepts": _concept_names(session, p.id),
            "summary": _summary(session, p.id),
        },
        ensure_ascii=False,
    )


def t_get_paper_full_text(session: Session, paper_id: int, max_chars: int = 6000) -> str:
    """The extracted full text of a paper (truncated), for close reading."""
    p = session.get(Paper, paper_id)
    if p is None or p.is_deleted:
        return json.dumps({"error": f"paper {paper_id} not found"})
    text = (p.full_text or "").strip()
    if not text:
        return json.dumps({"note": "no parsed full text for this paper"})
    max_chars = max(500, min(int(max_chars), 12000))
    return json.dumps(
        {"id": p.id, "title": p.title, "text": text[:max_chars] + ("…" if len(text) > max_chars else "")},
        ensure_ascii=False,
    )


def t_list_concepts(session: Session, min_papers: int = 1) -> str:
    """Concepts in the library, with how many papers each spans."""
    active_ids = _active_paper_ids(session)
    counts: dict[int, int] = {}
    for row in session.exec(select(PaperConcept)).all():
        if row.paper_id not in active_ids:
            continue
        counts[row.concept_id] = counts.get(row.concept_id, 0) + 1
    keep = {c for c, n in counts.items() if n >= min_papers}
    concepts = session.exec(select(Concept).where(Concept.id.in_(keep))).all()
    out = sorted(
        ({"name": c.name, "type": c.type, "papers": counts[c.id]} for c in concepts if c.id in keep),
        key=lambda d: -d["papers"],
    )
    return json.dumps(out or [{"note": "no concepts extracted yet"}], ensure_ascii=False)


def t_find_related(session: Session, paper_id: int) -> str:
    """Papers in the library that share concept(s) with the given paper."""
    p = session.get(Paper, paper_id)
    if p is None or p.is_deleted:
        return json.dumps({"error": f"paper {paper_id} not found"})
    my = {
        row.concept_id
        for row in session.exec(select(PaperConcept).where(PaperConcept.paper_id == paper_id)).all()
    }
    if not my:
        return json.dumps({"note": "this paper has no extracted concepts yet"})
    related: dict[int, set[int]] = {}
    active_ids = _active_paper_ids(session)
    for row in session.exec(select(PaperConcept).where(PaperConcept.concept_id.in_(my))).all():
        if row.paper_id == paper_id or row.paper_id not in active_ids:
            continue
        related.setdefault(row.paper_id, set()).add(row.concept_id)
    out: list[dict[str, Any]] = []
    for pid, cids in sorted(related.items(), key=lambda kv: -len(kv[1]))[:8]:
        rp = session.get(Paper, pid)
        if rp is not None and not rp.is_deleted:
            out.append({**_brief(rp), "shared_concepts": len(cids)})
    return json.dumps(out or [{"note": "no related papers in the library"}], ensure_ascii=False)


def t_tag_paper(session: Session, paper_id: int, tag_name: str, color: str | None = None) -> str:
    """Create/update a user tag and attach it to one paper."""
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        return json.dumps({"ok": False, "error": f"paper {paper_id} not found"}, ensure_ascii=False)
    try:
        tag, _ = create_or_update_tag(session, {"name": tag_name, "color": color})
        attached, _ = attach_tag_to_paper(session, paper_id, int(tag["id"]))
    except (LookupError, ValueError) as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps({"ok": True, "paper_id": paper_id, "tag": attached}, ensure_ascii=False)


def t_add_paper_to_collection(
    session: Session,
    paper_id: int,
    collection_name: str,
    description: str | None = None,
) -> str:
    """Create/update a user collection and add one paper to it."""
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        return json.dumps({"ok": False, "error": f"paper {paper_id} not found"}, ensure_ascii=False)
    try:
        collection, _ = create_or_update_collection(
            session,
            {"name": collection_name, "description": description},
        )
        added, _ = add_paper_to_collection(session, int(collection["id"]), paper_id)
    except (LookupError, ValueError) as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps({"ok": True, "paper_id": paper_id, "collection": added}, ensure_ascii=False)


TOOLS: list[Tool] = [
    Tool(
        name="search_library",
        description="Search the user's paper library by keyword. Returns matching papers with id, title, year, and a short abstract. Use this to find papers relevant to a topic.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword query (topic, method, dataset, author)."},
                "top_k": {"type": "integer", "description": "Max results to return.", "default": 5},
            },
            "required": ["query"],
        },
        run=t_search_library,
    ),
    Tool(
        name="get_paper",
        description="Get full metadata, the AI summary, and extracted concepts for one paper by id. Use after search_library or when a paper id is known.",
        parameters={
            "type": "object",
            "properties": {"paper_id": {"type": "integer", "description": "The paper's id."}},
            "required": ["paper_id"],
        },
        run=t_get_paper,
    ),
    Tool(
        name="get_paper_full_text",
        description="Read the extracted full text of a paper (truncated). Use for close reading or quoting details not in the abstract.",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "integer", "description": "The paper's id."},
                "max_chars": {"type": "integer", "description": "Max characters to return.", "default": 6000},
            },
            "required": ["paper_id"],
        },
        run=t_get_paper_full_text,
    ),
    Tool(
        name="list_concepts",
        description="List concepts (methods/datasets/problems/domains) extracted across the library, with how many papers each appears in.",
        parameters={
            "type": "object",
            "properties": {"min_papers": {"type": "integer", "description": "Only concepts in at least this many papers.", "default": 1}},
            "required": [],
        },
        run=t_list_concepts,
    ),
    Tool(
        name="find_related",
        description="Find other papers in the library that share concept(s) with a given paper.",
        parameters={
            "type": "object",
            "properties": {"paper_id": {"type": "integer", "description": "The paper's id."}},
            "required": ["paper_id"],
        },
        run=t_find_related,
    ),
    Tool(
        name="tag_paper",
        description="Create or reuse a user tag and attach it to one paper. Use after identifying a paper id. Good for organizing a master's library by topic, method, priority, or thesis role.",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "integer", "description": "The paper's id."},
                "tag_name": {"type": "string", "description": "User-visible tag name."},
                "color": {"type": "string", "description": "Optional CSS color, such as #2563eb."},
            },
            "required": ["paper_id", "tag_name"],
        },
        run=t_tag_paper,
    ),
    Tool(
        name="add_paper_to_collection",
        description="Create or reuse a user collection and add one paper to it. Use for durable folders such as thesis must-read, related work, experiment baseline, or advisor discussion.",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "integer", "description": "The paper's id."},
                "collection_name": {"type": "string", "description": "User-visible collection name."},
                "description": {"type": "string", "description": "Optional collection description."},
            },
            "required": ["paper_id", "collection_name"],
        },
        run=t_add_paper_to_collection,
    ),
]

_BY_NAME = {t.name: t for t in TOOLS}


def tool_schemas() -> list[dict[str, Any]]:
    return [t.schema() for t in TOOLS]


def get_tool(name: str) -> Tool | None:
    return _BY_NAME.get(name)
