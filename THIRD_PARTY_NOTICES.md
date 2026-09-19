# Third-party research skill notices

PaperMind includes two **adapted** research workflows. They are not the complete upstream skills, do not execute upstream hooks or scripts, and do not imply affiliation or endorsement. Upstream license and attribution notices are retained below and in `third_party/research_skills/`.

## Nature Skills — Apache License 2.0

- Project: https://github.com/Yuan1z0825/nature-skills
- Contributors: Yuan1z0825/nature-skills contributors.
- Pinned revision: `9ea7330a17813a15421fe843778a776c258b9001`.
- Original license: [Apache-2.0](third_party/research_skills/nature/LICENSE).
- Original files retained unchanged for provenance: `skills/nature-paper-card/SKILL.md` and `skills/nature-paper-card/references/evidence-and-provenance.md`, under [the upstream snapshot](third_party/research_skills/nature/skills/nature-paper-card/).
- **Changes made by PaperMind, 2026-09-15:** translated and condensed evidence categories, source coverage, claim-strength and contradiction handling into `backend/research_skills/paper-evidence/`; replaced the full 16-section card and upstream PDF/auditor workflow with PaperMind's existing paper tools and task output formats; added per-paper fact records, paginated tool navigation, and operation provenance. Adapted files carry modification notices and remain distributed under Apache-2.0.
- No applicable upstream NOTICE file was present for these selected files at the pinned revision. This document is PaperMind's attribution/modification notice, not an upstream NOTICE file.

## K-Dense Scientific Agent Skills — MIT

- Project: https://github.com/K-Dense-AI/scientific-agent-skills
- Copyright (c) 2025 K-Dense Inc.
- Upstream paper: Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026). _Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents_. https://doi.org/10.48550/arXiv.2609.00065
- Pinned revision: `330c8e764435a731eff571e3efdda70b363d0792`.
- Original license and full permission notice: [MIT](third_party/research_skills/kdense/LICENSE.md).
- Original files retained unchanged: `skills/scientific-critical-thinking/SKILL.md` and `references/core_capabilities.md`, under [the upstream snapshot](third_party/research_skills/kdense/skills/scientific-critical-thinking/).
- **Changes made by PaperMind, 2026-09-15:** translated and selected methodology, confounding, statistical uncertainty and claim-evaluation guidance into `backend/research_skills/critical-comparison/`; adapted it to bounded library evidence and existing JSON/Markdown outputs. Domain-specific grading, optional figure generation and external services are not included. Adapted files are distributed with the original MIT copyright and permission notice.

The upstream snapshots are attribution/reference material, not independently installed runnable skill packages. All runtime dependencies of the two PaperMind adaptations are contained in `backend/research_skills/`. The loader reads each entrypoint and its local reference explicitly. The source archive and Windows portable distribution include this notice, the original licenses and the selected upstream snapshots. Preserve these notices and license files when redistributing these components.

No Oh My Paper or Orchestra code/skill text is included in this integration.

Additional PaperMind implementation (2026-09-15): independent source-bound review with localized edits, short citation labels resolved to stable evidence identifiers, and documented provider-protocol adaptation. These additions do not claim to be upstream validators or to certify scientific truth; upstream attribution and license terms above remain unchanged.
