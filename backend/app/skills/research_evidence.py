"""Versioned, self-contained adaptations; independent of user-editable skills.

Load entrypoints together with their declared local references. These bundles
use only PaperMind's existing tools and never run upstream scripts or hooks.
"""
from pathlib import Path

from app.paths import backend_dir

BUNDLES = (
    ("paper-evidence", "references/provenance.md"),
    ("critical-comparison", "references/comparison.md"),
)


def research_skill_prompt(root: Path | None = None) -> str:
    root = root or backend_dir() / "research_skills"
    blocks = []
    for name, reference in BUNDLES:
        directory = root / name
        entry = (directory / "SKILL.md").read_text(encoding="utf-8")
        # Runtime instructions exclude discovery metadata and attribution prose.
        body = entry.split("---", 2)[-1].strip()
        body = "\n".join(line for line in body.splitlines() if not line.startswith("PaperMind 改编版"))
        details = (directory / reference).read_text(encoding="utf-8")
        details = "\n".join(line for line in details.splitlines() if not line.startswith("2026-09-15 由 PaperMind"))
        blocks.append(f"[内置科研技能 {name} v1]\n{body}\n\n{details}")
    return "\n\n".join(blocks)
