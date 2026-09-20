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

from app.models import Concept, Paper, PaperConcept, PaperExcerpt, PaperNote, ReviewMatrixEntry, Summary
from app.models.paper import parse_authors_json, parse_summary_json
from app.agent.clarification import question_request
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


def t_get_paper_full_text(
    session: Session, paper_id: int, max_chars: int = 6000,
    start_char: int = 0, query: str | None = None,
) -> str:
    """Read a bounded, navigable excerpt of the extracted paper text."""
    p = session.get(Paper, paper_id)
    if p is None or p.is_deleted:
        return json.dumps({"error": f"paper {paper_id} not found"})
    text = (p.full_text or "").strip()
    if not text:
        return json.dumps({"note": "no parsed full text for this paper"})
    max_chars = max(500, min(int(max_chars), 12000))
    start_char = max(0, min(int(start_char), len(text)))
    match_char = None
    if query and query.strip():
        match_char = text.lower().find(query.strip().lower(), start_char)
        if match_char < 0:
            return json.dumps({"id": p.id, "title": p.title, "total_chars": len(text),
                               "query": query, "match_found": False,
                               "note": "No exact phrase match after start_char; try a shorter keyword or read by offset."}, ensure_ascii=False)
        start_char = max(start_char, match_char - min(500, max_chars // 2))
    end_char = min(len(text), start_char + max_chars)
    return json.dumps(
        {"id": p.id, "title": p.title, "text": text[start_char:end_char],
         "start_char": start_char, "end_char": end_char, "total_chars": len(text),
         "truncated": start_char > 0 or end_char < len(text),
         "next_start_char": end_char if end_char < len(text) else None,
         **({"match_found": True, "match_char": match_char} if match_char is not None else {})},
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


# T7：检索用户自己的研究知识。片段与结果数受上限，排除软删除论文。
_RESEARCH_NOTE_SNIPPET_MAX = 280


def _clip_snippet(text: str | None, limit: int = _RESEARCH_NOTE_SNIPPET_MAX) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _matrix_joined(row: ReviewMatrixEntry) -> str:
    return " ".join(
        part
        for part in (
            row.problem,
            row.method,
            row.dataset,
            row.metrics,
            row.results,
            row.limitations,
            row.novelty,
            row.relation_to_thesis,
            row.future_work,
            row.notes,
        )
        if part
    )


def t_search_research_notes(session: Session, query: str, top_k: int = 8) -> str:
    """Keyword search over the user's own notes, excerpts and matrix rows.

    Pure keyword matching (whitespace tokens as case-insensitive substrings,
    Chinese included) — no vector index involved, nothing to rebuild.
    """
    tokens = [token.lower() for token in (query or "").split() if token.strip()]
    if not tokens:
        return json.dumps([{"note": "no matching research notes"}], ensure_ascii=False)
    top_k = max(1, min(int(top_k), 20))
    active = {
        paper.id: paper
        for paper in session.exec(select(Paper).where(Paper.is_deleted == False)).all()  # noqa: E712
        if paper.id is not None
    }

    def hits(text: str | None) -> int:
        low = (text or "").lower()
        return sum(1 for token in tokens if token in low)

    scored: list[tuple[int, dict[str, Any]]] = []
    for note in session.exec(select(PaperNote)).all():
        if note.paper_id not in active:
            continue
        score = hits(note.content)
        if not score:
            continue
        paper = active[note.paper_id]
        scored.append(
            (
                score,
                {
                    "type": "note",
                    "paper_id": note.paper_id,
                    "title": paper.title,
                    "kind": note.kind,
                    "snippet": _clip_snippet(note.content),
                    "locator": None,
                },
            )
        )
    for excerpt in session.exec(select(PaperExcerpt)).all():
        if excerpt.paper_id not in active:
            continue
        score = hits(f"{excerpt.quote} {excerpt.note or ''}")
        if not score:
            continue
        paper = active[excerpt.paper_id]
        scored.append(
            (
                score,
                {
                    "type": "excerpt",
                    "paper_id": excerpt.paper_id,
                    "title": paper.title,
                    "kind": None,
                    "snippet": _clip_snippet(excerpt.quote),
                    "locator": {
                        "page": excerpt.page,
                        "section": excerpt.section,
                        "locator": excerpt.locator,
                    },
                },
            )
        )
    for row in session.exec(select(ReviewMatrixEntry)).all():
        if row.paper_id not in active:
            continue
        joined = _matrix_joined(row)
        score = hits(joined)
        if not score:
            continue
        paper = active[row.paper_id]
        scored.append(
            (
                score,
                {
                    "type": "matrix",
                    "paper_id": row.paper_id,
                    "title": paper.title,
                    "kind": None,
                    "snippet": _clip_snippet(joined),
                    "locator": None,
                },
            )
        )

    scored.sort(key=lambda pair: -pair[0])
    out = [item for _score, item in scored[:top_k]]
    return json.dumps(out or [{"note": "no matching research notes"}], ensure_ascii=False)


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


def t_search_topic_wiki(session, query):
    from app.wiki.service import chat_topics
    return json.dumps(chat_topics(session,str(query)[:2000]),ensure_ascii=False)


TOOLS: list[Tool] = [
    Tool(
        name='search_topic_wiki',
        description='Search adopted topic knowledge in the current research workspace. Returns versioned pages, source snapshots, review status, source changes and page links. Candidate drafts are excluded.',
        parameters={'type':'object','properties':{'query':{'type':'string','maxLength':2000}},'required':['query'],'additionalProperties':False},
        run=t_search_topic_wiki,
    ),
    Tool(
        name="ask_user",
        description=(
            "Proactively ask the user 1–3 concise questions when their research goal, intended use, scope, "
            "or key constraints are unclear and would materially change the analysis or search direction. "
            "For substantive research or feasibility discussions, first understand relevant researcher background: "
            "role and research stage, skills, prior work, research direction, available data/equipment/compute, "
            "time and collaborators. Ask about important gaps before tailoring recommendations; use known "
            "project and conversation context and never repeat an already answered background questionnaire. "
            "Clarify before aimless searching. Do not require every detail before helping; use reasonable "
            "defaults for minor preferences and explore directly when the user asks for initial ideas. "
            "Provide up to 4 suggested answers per question if useful; "
            "the user can always write their own answer or skip. Do not ask about information already "
            "provided or available in the library. Call this tool alone, then wait for the real user response; "
            "never invent an answer. Avoid unnecessary confirmation and repeated questions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "maxLength": 600, "description": "Briefly explain why these details matter."},
                "questions": {
                    "type": "array", "minItems": 1, "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "minLength": 1, "maxLength": 600},
                            "options": {"type": "array", "maxItems": 4, "items": {"type": "string", "minLength": 1, "maxLength": 600}},
                        },
                        "required": ["question"], "additionalProperties": False,
                    },
                },
            },
            "required": ["questions"], "additionalProperties": False,
        },
        # The harness intercepts this tool and suspends instead of fabricating a result.
        run=lambda session, **kwargs: json.dumps(question_request(kwargs), ensure_ascii=False),
    ),
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
        description="Read a paper excerpt for close reading. Returns offsets, total length and next_start_char; a truncated excerpt is NOT the whole paper. For specific facts prefer query with a short exact phrase (e.g. 'Training' or 'Table 2') to locate relevant text without repeating the beginning. Use start_char=next_start_char to continue. Max 12000 characters per call; increasing max_chars beyond this does not reveal later sections.",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "integer", "description": "The paper's id."},
                "max_chars": {"type": "integer", "description": "Characters per excerpt, capped at 12000.", "default": 6000},
                "start_char": {"type": "integer", "description": "Zero-based character offset; use next_start_char from a previous result to continue.", "default": 0},
                "query": {"type": "string", "description": "Optional short case-insensitive exact phrase; searches at/after start_char and returns surrounding text. No match is not proof the paper lacks the concept."},
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
        name="search_research_notes",
        description=(
            "Search the user's OWN research notes, PDF excerpts, and review-matrix rows by keyword. "
            "Returns the asset type, paper id/title, a short snippet, and locator info (page/section "
            "for excerpts). Use this whenever the user asks about their own notes, highlights, "
            "comments, judgments, or review matrix — not search_library."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords to look for in notes/excerpts/matrix."},
                "top_k": {"type": "integer", "description": "Max results to return.", "default": 8},
            },
            "required": ["query"],
        },
        run=t_search_research_notes,
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
