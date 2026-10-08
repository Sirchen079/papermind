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
    return [str(author).strip() for author in parsed if str(author).strip()]


def _clean(value: object) -> str:
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def _line(tag: str, value: object | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return f"{tag}  - {_clean(value)}"


def format_paper(paper: Paper) -> str:
    # Split simple ranges; preserve article numbers/complex locators as SP.
    pages = (paper.pages or "").strip()
    match = re.fullmatch(r"([A-Za-z]*\d+)\s*(?:--|[-–—])\s*([A-Za-z]*\d+)", pages)
    start, end = match.groups() if match else (pages, None)
    lines = ["TY  - JOUR"]
    for maybe in [
        _line("TI", paper.title),
        _line("PY", paper.year),
        _line("JO", paper.venue),
        _line("VL", paper.volume),
        _line("IS", paper.issue),
        _line("SP", start),
        _line("EP", end),
        _line("DO", paper.doi),
        _line("AB", paper.abstract),
    ]:
        if maybe:
            lines.append(maybe)
    for author in _authors(paper):
        lines.append(f"AU  - {_clean(author)}")
    if paper.arxiv_id:
        lines.append(f"UR  - https://arxiv.org/abs/{_clean(paper.arxiv_id)}")
        lines.append(f"N1  - arXiv:{_clean(paper.arxiv_id)}")
    lines.append("ER  -")
    return "\n".join(lines)
