import re

_CITATION_KEY_RE = re.compile(r"^[A-Za-z0-9_.:+-]+$")


def normalize_citation_key(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if _CITATION_KEY_RE.fullmatch(text) is None:
        return None
    return text


def resolve_unique_citation_key(session, base: str, paper_id: int | None = None) -> str:
    """Resolve ``base`` to a citation key unique among non-deleted papers.

    Collisions get ``-a`` … ``-z`` suffixes (P10.4), then ``-27``, ``-28``, …
    so resolution always terminates deterministically.
    """
    from sqlalchemy import select

    from app.models import Paper

    base = normalize_citation_key(base) or "anon"

    def _taken(key: str) -> bool:
        conditions = [Paper.citation_key == key, Paper.is_deleted == False]  # noqa: E712
        if paper_id is not None:
            conditions.append(Paper.id != paper_id)
        return session.exec(select(Paper.id).where(*conditions)).first() is not None

    if not _taken(base):
        return base
    for i in range(26):
        candidate = f"{base}-{chr(ord('a') + i)}"
        if not _taken(candidate):
            return candidate
    n = 27
    while True:
        candidate = f"{base}-{n}"
        if not _taken(candidate):
            return candidate
        n += 1
