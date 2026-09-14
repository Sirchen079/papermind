"""Resolve current and portable PDF paths strictly within the library."""
from pathlib import Path


def resolve_pdf(value: str | None, root: Path) -> Path | None:
    if not value:
        return None
    root = root.resolve()
    path = Path(value)
    try:
        resolved = (path if path.is_absolute() else root / path).resolve()
        resolved.relative_to(root)
        if resolved.is_file():
            return resolved
        # Source checkouts historically stored data/pdfs/name.pdf relative to
        # the process directory. Keep those paths readable inside the same root.
        legacy = path.resolve()
        legacy.relative_to(root)
        return legacy if legacy.is_file() else None
    except (ValueError, OSError):
        return None


def finish_restore(engine, data_dir: Path) -> None:
    """Rebase legacy backup paths only after explicit offline restore.

    The marker is the backup manifest placed by restore.ps1. A candidate must
    match its relative filename AND hash, so a stale path is never guessed.
    """
    import hashlib
    import json
    from pathlib import PureWindowsPath
    from sqlmodel import Session, select
    from app.models import Paper

    marker = data_dir / "restore-manifest.json"
    if not marker.is_file():
        return
    manifest = json.loads(marker.read_text(encoding="utf-8-sig"))
    root = (data_dir / "pdfs").resolve()
    files = {entry["path"]: entry["sha256"] for entry in manifest["pdfs"]["files"]}
    with Session(engine) as session:
        for paper in session.exec(select(Paper).where(Paper.pdf_path != None)).all():
            if resolve_pdf(paper.pdf_path, root):
                continue
            parts = PureWindowsPath(paper.pdf_path).parts
            candidates = ["/".join(parts[i+1:]) for i, part in enumerate(parts) if part.lower() == "pdfs"]
            for relative in candidates:
                resolved = resolve_pdf(relative, root)
                if resolved and relative in files and hashlib.sha256(resolved.read_bytes()).hexdigest() == files[relative]:
                    paper.pdf_path = relative
                    session.add(paper)
                    break
        session.commit()
    marker.unlink()
