import json
import re

from app.models import Paper


def _authors(paper: Paper) -> list[str]:
    try:
        parsed = json.loads(paper.authors_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(author) for author in parsed if str(author).strip()]


def _escape(value: object) -> str:
    text = str(value)
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _title_word(title: str | None) -> str:
    for word in re.findall(r"[A-Za-z0-9]+", title or ""):
        if word.lower() not in {"a", "an", "the"}:
            return word.lower()
    return "paper"


def base_citekey(paper: Paper) -> str:
    """Generate the stable key `firstauthorYEARfirstword` (P10.4).

    First author's surname (lowercase, alnum only) + year + first title word
    (articles skipped). No usable author falls back to ``anon``; no year to
    ``nodate``; no usable title word to ``paper``.
    """
    authors = _authors(paper)
    first = "anon"
    if authors:
        surname = re.findall(r"[A-Za-z0-9]+", authors[0].split()[-1])
        if surname:
            first = surname[0].lower()
    year = str(paper.year) if paper.year else "nodate"
    return re.sub(r"[^a-z0-9]", "", f"{first}{year}{_title_word(paper.title)}") or "anon"


def citekey(paper: Paper) -> str:
    saved_key = str(paper.citation_key or "").strip()
    if saved_key:
        return saved_key
    # Legacy rows without a stored key keep the lazy fallback so old exports
    # never break; fresh ingests get the key persisted (P10.4).
    return base_citekey(paper)


def format_paper(paper: Paper, key: str) -> str:
    fields: list[tuple[str, object | None]] = [
        ("title", paper.title),
        ("author", " and ".join(_authors(paper)) or None),
        ("year", paper.year),
        ("journal", paper.venue),
        ("doi", paper.doi),
        ("eprint", paper.arxiv_id),
    ]
    if paper.arxiv_id:
        fields.append(("archivePrefix", "arXiv"))
    fields.append(("abstract", paper.abstract))

    lines = [f"@article{{{key},"]
    for name, value in fields:
        if value is not None and str(value).strip():
            lines.append(f"  {name} = {{{_escape(value)}}},")
    if len(lines) > 1:
        lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)
