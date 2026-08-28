import re

_CITATION_KEY_RE = re.compile(r"^[A-Za-z0-9_.:+-]+$")


def normalize_citation_key(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if _CITATION_KEY_RE.fullmatch(text) is None:
        return None
    return text
