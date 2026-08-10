# Documentation System

Mardas Folio documentation follows a **guide-first** model. The English and Persian guides are the canonical user manuals, the feature references, and the official live rendering samples. Supporting documents under `docs/` are limited to operations, release discipline, security boundaries, changelog history, and documentation policy.

## Goals

The documentation has four jobs:

1. teach users how to install, configure, and use the converter;
2. demonstrate every user-facing renderer feature with real Markdown samples;
3. keep release, maintenance, and security workflows reproducible;
4. keep generated guide PDFs rebuildable and visually reviewable.

## Documentation map

| File | Ownership | Release responsibility |
| :--- | :--- | :--- |
| `README.md` | Project landing page, short overview, quick start, and links. | Keep concise; link to the guides and operations docs. |
| `docs/README.md` | Directory index for the guide-first documentation model. | Update whenever docs are added, removed, or reclassified. |
| `docs/guides/GUIDE.en.md` | Complete English user manual, feature reference, and live rendering sample. | Must teach user-facing features and start with valid YAML front matter. |
| `docs/guides/GUIDE.fa.md` | Complete Persian user manual and RTL/Persian live rendering sample. | Must mirror user-facing coverage while preserving Persian readability and RTL samples. |
| `examples/GUIDE.en.pdf` | Generated English guide PDF. | Rebuild with `scripts/build_examples.sh`; never hand-edit. |
| `examples/GUIDE.fa.pdf` | Generated Persian guide PDF. | Rebuild with `scripts/build_examples.sh`; visually inspect RTL output. |
| `docs/CHANGELOG.md` | Release ledger. | Keep descending, accurate, and free of roadmap entries. |
| `docs/RELEASE.md` | Release checklist and artifact workflow. | Update when release mechanics or gates change. |
| `docs/MAINTENANCE.md` | Routine local checks, examples, distributions, and patch hygiene. | Update when scripts or local QA workflow changes. |
| `docs/SECURITY.md` | Trust boundaries and reporting. | Update when input, HTML, asset, Studio, sandbox, or metadata security changes. |

## Retired feature-reference pages

Standalone feature/reference pages such as appearance, branding, Markdown fidelity, PDF navigation, PDF typography, Persian/RTL, Studio, and visual QA notes were retired. Their user-facing content belongs in the guides, and their release/maintenance checks belong in `docs/MAINTENANCE.md`, `docs/RELEASE.md`, `docs/SECURITY.md`, tests, or scripts. Do not recreate those pages unless a feature becomes too large for the guides and has a clear non-user maintenance contract.

## Guide coverage policy

The guide files must remain valid Markdown documents with valid YAML front matter at byte zero:

```text
---
title: ...
...
---
```

Do not place explanatory prose before the front matter. Doing so prevents metadata extraction and causes the guide cover to fall back to generic values such as `Generated Document`.

The guides must cover at least these user-facing areas:

- installation and first PDF workflow;
- front matter, cover metadata, branding, and watermarks;
- language selection, direction, Persian/RTL behavior, mixed text, punctuation, and numerals;
- table of contents, PDF outline/bookmarks, metadata, page labels, and running footers;
- Markdown feature support, GitHub-style alerts, details, links, lists, tables, and page breaks;
- MathJax formulas;
- fenced, indented, titled, numbered, highlighted, and advanced code blocks;
- Mermaid `flowchart` / `graph` diagrams with node and edge labels; advanced Mermaid diagram types are intentionally outside the offline subset;
- local images, safe HTML images, blocked placeholders, and semantic captions;
- page flow, margins, page sizes, wide tables, code blocks, captions, footnotes, and final checklist;
- Studio GUI workflow, CLI workflow, automation, and preflight checks.

## Asset layout policy

Runtime packaged assets belong in `src/mardas_md2pdf/assets/`. The packaged logo files are `mardas-md2pdf-logo.png`, `mardas-md2pdf-logo-white.png`, `mardas-md2pdf-mark.svg`, `mardas-md2pdf-mark-white.svg`, `mardas-md2pdf-app-icon.svg`, and `mardas-md2pdf-mark-gui-mask.svg`.

Guide sample media belongs in `docs/guides/images/` and should remain lightweight. The guide currently uses `logo.png` and `architecture.png` as local documentation media. `assets/readme/mardas-folio.png` is repository-level artwork for the landing page and should not be embedded into the guides as a renderer sample. Users should use `brand.logo` only for their own organization or lab logo, not to re-embed the built-in project logo by default.

## Changelog policy

`docs/CHANGELOG.md` is the release ledger. Keep it structured as:

```text
# Changelog

All notable changes...

## x.y.z - YYYY-MM-DD

### Added / Changed / Fixed / Documentation / Tests

- Concrete user-visible or maintainer-visible change.
```

Rules:

- entries are sorted newest to oldest;
- each version appears once;
- generated guide PDF refreshes belong in the same release patch as the source change;
- development/audit artifacts should not be committed unless they are intended as permanent tooling;
- when a release patch changes user-facing behavior, bump version metadata and refresh the guide PDFs through `scripts/build_examples.sh`.

## Historical changelog reconstruction

The detailed pre-`1.5.0` changelog entries are reconstructed from the public baseline, early project documentation, and the feature set that existed before structured release notes began. They are not intended to imply that every older milestone was tagged as a published GitHub release. Keep the reconstruction conservative:

- describe capabilities that are visible in the baseline code or documentation;
- avoid inventing external release dates, distribution channels, or user counts;
- keep uncertain history under `Notes` rather than `Added` or `Fixed`;
- prefer broad version-shaped milestones such as `1.4.0` GUI baseline or `1.3.0` Markdown feature expansion when exact early patch tags are unavailable.

## Local verification

Before publishing documentation or PDF-output changes, run the normal project checks after installing development dependencies:

```bash
pip install -e .[dev]
python -m pytest -q
MARDAS_RENDER_SMOKE=1 bash scripts/check.sh
bash scripts/build_examples.sh
bash scripts/build_dist.sh
```

For guide-specific issues, visually inspect at least:

- the cover page;
- table of contents pages;
- one code-heavy page;
- one Mermaid page;
- one image/media page;
- the final footnote/checklist page;
- the same areas in the Persian guide.

Visual QA artifact scripts write under `build/` and their outputs must not be committed unless the project intentionally promotes a sample to permanent documentation or tooling. No roadmap file is part of this documentation set.
