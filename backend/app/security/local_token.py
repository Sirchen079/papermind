"""Local API token (P16): a per-installation credential for high-risk endpoints.

Mirrors :mod:`app.security.master_key` in style — a secret file living in the
data directory, outside version control, resolved through ``app.paths`` so dev,
tests (``PAPERMIND_DATA_DIR``) and frozen builds all agree.

The token is served to the SPA via a ``<meta>`` tag injected into
``dist/index.html`` (see ``app.main.inject_local_token``) and can be attached
by local callers as the ``X-Local-Token`` header, guarded by the
:func:`require_local_token` dependency below.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException

from app import paths

TOKEN_FILENAME = "api_token"


def _token_path() -> Path:
    return paths.default_data_dir() / TOKEN_FILENAME


def get_or_create_token() -> str:
    """Return the local API token, generating it on first use.

    Reads ``<data dir>/api_token`` if present (stripped), otherwise generates
    ``secrets.token_urlsafe(32)`` and writes it. A file that strips to an
    empty string is NOT trusted: the token is regenerated and the file
    overwritten (a blank stored token must never become a usable credential).
    Publication is atomic and serialized with other creators. The temporary
    file uses mode ``0600`` on POSIX.
    """
    return _read_token(_token_path())


def _read_token(path: Path) -> str:
    from app.security.secret_file import read_or_create
    return read_or_create(path, lambda: secrets.token_urlsafe(32).encode('utf-8'),
                          lambda value: bool(value.decode('utf-8').strip())).decode('utf-8').strip()


@lru_cache(maxsize=8)
def _cached_token(path: str) -> str:
    return _read_token(Path(path))


def reset_token_cache() -> None:
    """Drop the cached token so the next check re-resolves from disk (tests)."""
    _cached_token.cache_clear()


def require_local_token(
    x_local_token: str | None = Header(default=None, alias="X-Local-Token"),
) -> str:
    """FastAPI dependency: reject requests without the current local token.

    Fail-closed: when the resolved current token is empty, every request is
    rejected with 403 regardless of the provided header — an empty
    ``X-Local-Token`` must never match an empty token via compare_digest.
    """
    current = _cached_token(str(_token_path().resolve()))
    provided = x_local_token
    if (
        not current
        or provided is None
        or not secrets.compare_digest(provided.encode("utf-8"), current.encode("utf-8"))
    ):
        raise HTTPException(status_code=403, detail="local token required")
    return provided
