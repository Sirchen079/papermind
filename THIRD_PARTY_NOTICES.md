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

The 2026-09-15 adaptations did not include Oh My Paper or Orchestra source. The complete built-in skill libraries added in 0.6.1 are described below.

Additional PaperMind implementation (2026-09-15): independent source-bound review with localized edits, short citation labels resolved to stable evidence identifiers, and documented provider-protocol adaptation. These additions do not claim to be upstream validators or to certify scientific truth; upstream attribution and license terms above remain unchanged.


## Complete built-in skill libraries — 2026-09-25

PaperMind 0.6.1 also distributes the original skill resources in `backend/builtin_skills/`. These are separate from the older condensed adaptations above. They are available locally in both source and desktop distributions. `catalog.json` records every resource SHA256 and the exact family inventory. Runtime routing and the PaperMind task adapter are implemented separately in `backend/app/skills/builtin.py`; upstream resource text is preserved.

### Nature Skills (complete installed collection)

- Upstream: https://github.com/Yuan1z0825/nature-skills
- Verified against revision `9e2d90e2171a61dc0ae072e43e8d16e3fc73572f`.
- All 20 skill directories, including `nature-shared`, and every upstream skill resource are present: 747 skill files plus the Apache-2.0 license.
- The local installed collection matches this upstream revision except two pre-existing local modifications retained in `nature-academic-search/scripts/format-converter.py` and `nature-citation/scripts/nature_citation.py`. PaperMind did not modify their contents during integration; their exact hashes are recorded in the catalog.
- License: `backend/builtin_skills/nature/LICENSE` (Apache-2.0). Copyright belongs to the Nature Skills contributors and retained per-file authors. No upstream root NOTICE is added or implied.
- PaperMind adaptation: task-based loading, Chinese output preference, existing model/tool integration, and non-blocking drafting behavior live outside the original resources. Bundled scripts and external-service instructions are preserved; their presence does not mean every external dependency or account is configured.

### Oh My Paper (complete skills directory)

- Upstream: https://github.com/LigphiDonk/Oh-my--paper
- Pinned revision: `6baece9f13324c209592124ebc213289336f26c3`.
- All 35 skill directories and their resources are retained, together with upstream README files and LICENSE: 224 files total.
- Copyright (c) 2026 donkfeng. MIT license and permission notice: `backend/builtin_skills/oh-my-paper/LICENSE`. Per-file upstream attribution and license notices are preserved.
- PaperMind does not install or run the upstream Claude Code plugin, session hooks, or remote-experiment machinery. It loads the actual skill resources through its own skill tools. Current library reviews use academic-researcher and research-paper-handoff alongside Nature Writing.

### PaperSpark research reference

- Inspected project: https://github.com/zongxi1115/PaperSpark at revision `8703a784e0668a96649300b935caf5fa97150fcd`.
- Its license is CC BY-NC 4.0, copyright (c) 2026 The PaperSpark Authors. License: https://github.com/zongxi1115/PaperSpark/blob/8703a784e0668a96649300b935caf5fa97150fcd/LICENSE
- This release does not copy or distribute PaperSpark source, prompts, images or assets. The design study is documented in `docs/paperspark-reference.md`. Any future direct reuse must separately satisfy its attribution, modification and noncommercial conditions or obtain other permission.
### OCR Markdown normalization

- HTML tables returned by OCR are converted with `python-markdownify` 1.2.3 (MIT), https://github.com/matthewwithanm/python-markdownify. Copyright 2012–2018 Matthew Tretter. Original permission notice: `third_party/ocr_markdown/markdownify-LICENSE`.
- Its parser dependencies are Beautiful Soup 4.15.0 (MIT) and Soup Sieve 2.10 (MIT). Original notices: `third_party/ocr_markdown/beautifulsoup4-LICENSE` and `third_party/ocr_markdown/soupsieve-LICENSE.md`.
- PaperMind expands recognized merged-cell labels before conversion and keeps table rows and repeated headers together during chunking. OCR is requested from the user's configured model connection; no model weights, user keys or connection configurations are bundled.

# Markdown parsing reused for resource links

The frontend already uses unified and remark through react-markdown/remark-gfm.
Version 0.6.26 declares unified 11.0.5 and remark-parse 11.0.0 directly to reuse
the same parser when repairing Chinese prose boundaries around bare URLs.
No upstream parser code is copied or modified. Their MIT copyright and
permission notices are retained at `third_party/markdown_render/unified-LICENSE`
and `third_party/markdown_render/remark-parse-LICENSE`.

# Bundled local inference runtime

PaperMind bundles the unmodified Windows CPU server and DLLs from
[llama.cpp b11146](https://github.com/ggml-org/llama.cpp/releases/tag/b11146).
The downloaded archive SHA256 is `14cf1303ca9ac3abd94816850532f9f9a69ac66fbaca3776fc6f9061c2fac1d1`.
llama.cpp is distributed under MIT; the original license is retained at
`third_party/llama_cpp/LICENSE`. The release's LLVM OpenMP license is retained at
`third_party/llama_cpp/LICENSE-LLVM-OpenMP`. Upstream vendor sources and license
files are preserved under `third_party/llama_cpp/upstream/`, including their
individual copyright notices. PaperMind's runtime management code is separate
from these unmodified components. Model weights are imported by the user and
are not included in the installer; each model retains its own license.
