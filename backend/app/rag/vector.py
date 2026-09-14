"""float32 embedding (de)serialization + cosine ranking (no numpy dependency).

Embeddings are stored as float32 BLOBs in the ``paperchunk`` table. Ranking is
brute-force cosine similarity — fine for a local single-user library: the
sqlite-vec loadable extension isn't guaranteed available on Windows-bundled
SQLite, and switching embedding models already requires re-embedding everything
(anyway incompatible by dimensionality). For a few thousand chunks this is a
few-millisecond scan, dominated by the embedding API round-trip.
"""
from __future__ import annotations

import math
from array import array
from collections.abc import Iterable
from typing import Any

# IEEE-754 single precision. array uses the platform's native byte order
# (little-endian on x86 / ARM-LE); write and read happen on the same machine.
_FLOAT = "f"


def serialize(vec: list[float]) -> bytes:
    """Encode a vector as a float32 byte string."""
    return array(_FLOAT, vec).tobytes()


def deserialize(blob: bytes) -> array:
    """Decode a float32 byte string back into a vector."""
    return array(_FLOAT, blob)


def _norm(vec: Iterable[float]) -> float:
    return math.sqrt(sum(x * x for x in vec))


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    na, nb = _norm(a), _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def top_k(
    query: list[float],
    items: list[tuple[Any, list[float]]],
    k: int,
) -> list[tuple[Any, float]]:
    """Return the ``k`` items most similar to ``query`` by cosine similarity.

    ``items`` is a list of ``(key, vector)`` pairs; the result is a list of
    ``(key, score)`` sorted by descending score.
    """
    qn = _norm(query)
    if qn == 0.0 or not items:
        return []
    scored: list[tuple[Any, float]] = []
    for key, vec in items:
        vn = _norm(vec)
        if vn == 0.0:
            continue
        scored.append((key, sum(x * y for x, y in zip(query, vec)) / (qn * vn)))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]
