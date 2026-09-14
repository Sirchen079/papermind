"""Line-aware text chunking for paper retrieval.

PDF-extracted text is line-oriented, so we pack whole lines up to a target
length — chunks stay coherent (no mid-sentence splits in the common case) — and
hard-split any single line that alone exceeds the target.
"""

def chunk_text(text: str, target: int = 1000) -> list[str]:
    text = text or ""
    if not text.strip():
        return []
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    chunks: list[str] = []
    buf = ""
    for ln in lines:
        if not buf:
            buf = ln
        elif len(buf) + 1 + len(ln) <= target:
            buf = f"{buf} {ln}"
        else:
            chunks.append(buf)
            buf = ln
    if buf:
        chunks.append(buf)

    # Hard-split any chunk still over the target (very long single lines).
    out: list[str] = []
    for c in chunks:
        while len(c) > target:
            out.append(c[:target])
            c = c[target:]
        if c:
            out.append(c)
    return out
