"""Rule-first reference extraction from ingested full text (P8.2).

Pipeline position: called by ``ingestion/service.py`` after the paper row is
persisted — no new pipeline stage. Rule parsing (section location, entry
splitting, field regexes) always runs and needs no LLM; the summary-role model
is only asked to structure the section when rules fail to find >= 3 titled
entries. Any failure degrades to keeping the raw reference strings.
"""

import json
import re

from sqlmodel import Session, select

from app.ingestion.dedup import normalize_title
from app.models import Paper, PaperCitation

# Minimum parsed entries before we trust rule-based extraction.
_MIN_RULED_ENTRIES = 3
# Minimum References-section length (chars) before the LLM fallback is worth a call.
_MIN_SECTION_FOR_LLM = 300

_SECTION_RE = re.compile(
    r"^\s*(references|reference list|bibliography|literature cited|works cited)\s*[:.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_APPENDIX_RE = re.compile(
    r"^\s*(appendix|appendices|supplementary|acknowledg(e)?ments?)\b",
    re.IGNORECASE | re.MULTILINE,
)
_NUMBERED_RE = re.compile(r"^(?:\[\d+\]|\d+[.)])\s+")
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;\"'\]]+)")
_ARXIV_RE = re.compile(r"arxiv:?\s*([a-z-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

_VENUE_PREFIXES = (
    "in ",
    "in:",
    "proceedings",
    "advances in",
    "journal",
    "transactions",
    "ieee",
    "acm",
    "pp",
    "pages",
    "vol",
    "volume",
    "arxiv",
    "doi",
    "http",
    "preprint",
)
_CONNECTORS = {"and", "et", "al.", "al", "&"}

_LLM_PROMPT = """你是一名参考文献解析专家。下面是论文的参考文献章节原文。请把它解析为 JSON 数组，每个元素恰好包含以下键：
{{"raw_ref": "原始参考文献文本", "title": "论文标题", "doi": "DOI 或空字符串", "arxiv_id": "arXiv 编号或空字符串", "year": 出版年份或 null, "authors": ["作者名", ...]}}
仅返回 JSON 数组本身（不要任何解释文字，不要 markdown 代码块标记）。

参考文献章节原文（已截断）：
{section}"""


def extract_references_section(full_text: str | None) -> str | None:
    """Return the text of the last References/Bibliography section, if any.

    The LAST match is used so a table-of-contents mention doesn't shadow the
    real section; anything after an Appendix/Acknowledgements heading is cut.
    """
    if not full_text:
        return None
    matches = list(_SECTION_RE.finditer(full_text))
    if not matches:
        return None
    section = full_text[matches[-1].end() :]
    appendix = _APPENDIX_RE.search(section)
    if appendix:
        section = section[: appendix.start()]
    section = section.strip()
    return section or None


def split_references(section: str) -> list[str]:
    """Split a References section into raw entry strings.

    Numbered styles ([1] / 1. / 1)) open a new entry; every other non-empty
    line continues the previous one (PDF text extraction rarely keeps an entry
    on a single line). Untitled noise (page headers, the heading itself) is
    dropped by the length floor.
    """
    lines = [
        ln.strip()
        for ln in section.splitlines()
        if ln.strip() and not re.fullmatch(r"(references|bibliography)\s*", ln.strip(), re.IGNORECASE)
    ]
    entries: list[str] = []
    for ln in lines:
        if _NUMBERED_RE.match(ln) or not entries:
            entries.append(ln)
        else:
            entries[-1] = f"{entries[-1]} {ln}"
    return [e for e in entries if len(e) >= 10]


def _looks_like_authors(part: str) -> bool:
    words = part.replace(",", " ").split()
    if not words:
        return True
    if any(w.lower() in _CONNECTORS for w in words):
        return True
    initials = sum(1 for w in words if re.fullmatch(r"[A-Z]\.?", w))
    return initials >= max(1, len(words) // 2) and len(words) <= 8


def _looks_like_venue(part: str) -> bool:
    low = part.lower()
    return any(low.startswith(prefix) for prefix in _VENUE_PREFIXES)


def _guess_title(parts: list[str]) -> tuple[str | None, int]:
    """Pick the title sentence among reference parts.

    Returns (title, index) so callers know where the author block ended.
    Heuristic: the first sentence that is neither an author fragment (initials,
    ``and``/``et al.``) nor a venue fragment (``In Proceedings ...``, ``pp.
    ...``) and is long enough to be a title.
    """
    for i, part in enumerate(parts):
        if _looks_like_authors(part) or _looks_like_venue(part):
            continue
        if len(part) >= 10 and part[:1].isupper():
            return part.rstrip(".").strip(), i
    return None, -1


def _guess_authors(parts: list[str], title_index: int) -> list[str]:
    if title_index <= 0:
        return []
    tokens: list[str] = []
    for part in parts[:title_index]:
        for chunk in re.split(r",+|\band\b|&", part):
            name = chunk.strip(" .")
            if len(name) >= 2 and name[:1].isupper() and not name[:1].isdigit():
                tokens.append(name)
    return tokens[:10]


def parse_reference(raw: str) -> dict:
    """Best-effort field parse of one raw reference string."""
    body = _NUMBERED_RE.sub("", raw).strip()
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", body) if p.strip()]
    title, title_index = _guess_title(parts)

    ref = {"raw_ref": raw, "title": title}
    if doi := _DOI_RE.search(body):
        ref["doi"] = doi.group(1).rstrip(".")
    if arxiv := _ARXIV_RE.search(body):
        ref["arxiv_id"] = arxiv.group(1).lower()
    if year := _YEAR_RE.search(body):
        ref["year"] = int(year.group(1))
    if authors := _guess_authors(parts, title_index):
        ref["authors"] = authors
    return ref


def _llm_parse_references(client, provider, model_id: str, section: str) -> list[dict]:
    result = client.complete(
        provider,
        model_id,
        [{"role": "user", "content": _LLM_PROMPT.format(section=section[:6000])}],
        request_kind="ingest",
    )
    text = (result.content or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("expected a JSON array of references")
    refs = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("raw_ref") or "").strip()
        if not raw:
            continue
        year = item.get("year")
        refs.append(
            {
                "raw_ref": raw,
                "title": (str(item.get("title")).strip() or None) if item.get("title") else None,
                "doi": (str(item.get("doi")).strip() or None) if item.get("doi") else None,
                "arxiv_id": (str(item.get("arxiv_id")).strip() or None) if item.get("arxiv_id") else None,
                "year": int(year) if isinstance(year, (int, str)) and str(year).isdigit() else None,
                "authors": [str(a) for a in item.get("authors") or [] if str(a).strip()][:10],
            }
        )
    return refs


def extract_citations(
    full_text: str | None,
    client=None,
    provider=None,
    model_id: str | None = None,
) -> list[dict]:
    """Extract parsed reference dicts from a full text.

    Rule-based first; LLM fallback (summary-role model) only when rules found
    fewer than _MIN_RULED_ENTRIES titled entries AND the section is long
    enough AND an LLM is configured. LLM failure degrades to the ruled result.
    """
    section = extract_references_section(full_text)
    if not section:
        return []
    ruled = [parse_reference(raw) for raw in split_references(section)]
    titled = [r for r in ruled if r.get("title")]
    if len(titled) >= _MIN_RULED_ENTRIES or client is None or provider is None or not model_id:
        return ruled
    if len(section) < _MIN_SECTION_FOR_LLM:
        return ruled
    try:
        llm_refs = _llm_parse_references(client, provider, model_id, section)
    except Exception:  # noqa: BLE001 — LLM is a fallback, never a hard dependency
        return ruled
    if not llm_refs:
        return ruled
    # Prefer LLM entries; keep ruled entries the LLM missed (by normalized title).
    seen_norms = {normalize_title(r.get("title")) for r in llm_refs if r.get("title")}
    merged = list(llm_refs)
    for r in ruled:
        norm = normalize_title(r.get("title"))
        if norm and norm not in seen_norms:
            merged.append(r)
    return merged


def store_citations(session: Session, paper: Paper, refs: list[dict]) -> int:
    """Upsert parsed refs as PaperCitation rows; returns inserted count.

    Idempotent on (source_paper_id, ref_title_norm): re-extraction inserts
    nothing new. Refs without a normalized title always insert (SQLite unique
    indexes treat NULL as distinct).
    """
    existing = {
        row.ref_title_norm
        for row in session.exec(
            select(PaperCitation).where(PaperCitation.source_paper_id == paper.id)
        ).all()
    }
    inserted = 0
    for ref in refs:
        title = (ref.get("title") or "").strip() or None
        norm = normalize_title(title) or None
        if norm and norm in existing:
            continue
        session.add(
            PaperCitation(
                source_paper_id=paper.id,
                raw_ref=ref.get("raw_ref") or "",
                ref_title=title,
                ref_title_norm=norm,
                ref_doi=(ref.get("doi") or None),
                ref_arxiv_id=(ref.get("arxiv_id") or None),
                ref_year=ref.get("year"),
                ref_authors_json=json.dumps(ref.get("authors") or [], ensure_ascii=False),
            )
        )
        if norm:
            existing.add(norm)
        inserted += 1
    if inserted:
        session.commit()
    return inserted


def extract_and_store_citations(
    session: Session,
    paper: Paper,
    client=None,
    provider=None,
    model_id: str | None = None,
) -> int:
    """Ingest-time entry point: extract + store; never raises."""
    try:
        if not paper.full_text:
            return 0
        refs = extract_citations(paper.full_text, client, provider, model_id)
        if not refs:
            return 0
        return store_citations(session, paper, refs)
    except Exception:  # noqa: BLE001 — citation extraction must not abort ingest
        return 0
