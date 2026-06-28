import re
import unicodedata


def normalize_title(title: str | None) -> str:
    """Normalize a paper title for fuzzy dedup.

    Lowercase, strip accents, replace punctuation with spaces, collapse
    whitespace. Two titles that differ only in case/accents/punctuation
    map to the same key.
    """
    if not title:
        return ""
    s = unicodedata.normalize("NFKD", title)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
