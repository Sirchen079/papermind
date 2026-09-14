import json
from pathlib import Path

from sqlmodel import Session, select

from app.models import Skill


def parse_skill_file(path: Path) -> dict:
    """Parse a Markdown skill file with simple YAML-ish frontmatter.

    Frontmatter is a leading ``---``-delimited block of ``key: value`` lines
    (no nested structures); the rest is the skill body. ``keywords`` is a
    comma-separated list.
    """
    text = Path(path).read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = text
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = parts[2].strip()

    name = meta.get("name") or Path(path).stem
    keywords = [k.strip() for k in (meta.get("keywords") or "").split(",") if k.strip()]
    return {
        "name": name,
        "description": meta.get("description"),
        "type": meta.get("type") or "instruction",
        "trigger": meta.get("trigger") or "manual",
        "keywords_json": json.dumps(keywords),
        "model_role": meta.get("model_role"),
        "body": body,
        "source": "user",
        "file_path": str(path),
    }


def load_skills_from_dir(session: Session, skills_dir: Path, *, overwrite: bool = True) -> int:
    """Scan ``skills_dir/*.md`` and load into the DB. Returns count of files found.

    ``overwrite=True`` (the default, used by the manual 'reload' action) refreshes
    existing rows from disk. ``overwrite=False`` is insert-only — a skill already
    in the DB is left untouched, so startup auto-load never clobbers a skill the
    user edited in the UI.
    """
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return 0
    count = 0
    for md in sorted(skills_dir.glob("*.md")):
        data = parse_skill_file(md)
        existing = session.exec(select(Skill).where(Skill.name == data["name"])).first()
        if existing is not None:
            if overwrite:
                for key, value in data.items():
                    setattr(existing, key, value)
                session.add(existing)
        else:
            session.add(Skill(**data))
        count += 1
    session.commit()
    return count
