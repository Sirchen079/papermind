"""P11.1 backend PDF file service tests (incl. path-traversal protection)."""
from pathlib import Path

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper


def _add_paper(pdf_path: str | None, *, deleted: bool = False) -> int:
    with Session(get_engine()) as session:
        paper = Paper(source="pdf", title="File Paper", pdf_path=pdf_path, is_deleted=deleted)
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper.id


def _pdf_root(env) -> Path:
    root = Path(env) / "data" / "pdfs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_paper_file_serves_pdf_bytes(client, env):
    root = _pdf_root(env)
    pdf = root / "2501.00001.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    pid = _add_paper(str(pdf))

    resp = client.get(f"/api/papers/{pid}/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert b"%PDF-1.4" in resp.content


def test_paper_file_404_for_missing_paper_soft_deleted_or_no_pdf(client, env):
    assert client.get("/api/papers/9999/file").status_code == 404

    root = _pdf_root(env)
    pdf = root / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    deleted_id = _add_paper(str(pdf), deleted=True)
    assert client.get(f"/api/papers/{deleted_id}/file").status_code == 404

    no_pdf_id = _add_paper(None)
    assert client.get(f"/api/papers/{no_pdf_id}/file").status_code == 404

    ghost_id = _add_paper(str(root / "ghost.pdf"))  # path inside root, file gone
    assert client.get(f"/api/papers/{ghost_id}/file").status_code == 404


def test_paper_file_blocks_traversal_outside_pdf_root(client, env):
    """A tampered pdf_path must never escape the <data_dir>/pdfs root."""
    secret = Path(env) / "secret.txt"
    secret.write_text("top secret")

    # Absolute path outside the root.
    absolute_id = _add_paper(str(secret))
    assert client.get(f"/api/papers/{absolute_id}/file").status_code == 404

    # Relative ../ traversal that resolves outside the root.
    relative_id = _add_paper("../secret.txt")
    assert client.get(f"/api/papers/{relative_id}/file").status_code == 404

    # Deep traversal through an inner directory.
    sneaky_id = _add_paper(str(_pdf_root(env) / "sub" / ".." / ".." / "secret.txt"))
    assert client.get(f"/api/papers/{sneaky_id}/file").status_code == 404

    # .. that stays inside the root is legitimate (resolves to root/inner.pdf).
    root = _pdf_root(env)
    (root / "sub").mkdir(exist_ok=True)
    (root / "inner.pdf").write_bytes(b"%PDF-1.4 inner")
    inside_id = _add_paper(str(root / "sub" / ".." / "inner.pdf"))
    resp = client.get(f"/api/papers/{inside_id}/file")
    assert resp.status_code == 200
    assert b"%PDF-1.4 inner" in resp.content
