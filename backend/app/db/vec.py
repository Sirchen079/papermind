"""sqlite-vec availability flag.

The SQLite shipped with some Python builds (notably the default Windows
installer) is compiled without loadable-extension support, so loading
sqlite-vec can fail. We track availability so callers can gate vector
features; the engine sets it on each connection attempt.
"""
import logging

_log = logging.getLogger(__name__)

# None = not yet attempted on a real connection; True/False afterwards.
_available: bool | None = None


def mark_available(ok: bool) -> None:
    global _available
    if _available is None and not ok:
        _log.warning("sqlite-vec unavailable — vector features disabled")
    _available = ok


def vec_available() -> bool:
    return bool(_available)
