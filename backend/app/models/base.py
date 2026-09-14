from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC timestamp.

    Stored as UTC by convention; tzinfo is dropped for clean SQLite
    DateTime storage and round-tripping. This is the non-deprecated
    replacement for ``datetime.utcnow()`` (deprecated in Python 3.12).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_iso(value: datetime) -> str:
    """Serialize SQLite's naive UTC timestamps with an explicit timezone."""
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
