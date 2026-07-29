# Mardas MD2PDF

> **Professional Markdown to PDF converter for Persian, English, and mixed RTL/LTR technical documents**

![Language](https://img.shields.io/badge/Language-Python-blue) ![Renderer](https://img.shields.io/badge/Renderer-Playwright%20%2B%20Chromium-green) ![Math](https://img.shields.io/badge/Math-MathJax-purple) ![Version](https://img.shields.io/badge/Version-v1.23.0-success) ![Status](https://img.shields.io/badge/Status-Stable-success) ![CI](https://github.com/mragetsars/Mardas-MD2PDF/actions/workflows/ci.yml/badge.svg)

## Overview

This repository contains **Mardas MD2PDF**, a Markdown-to-PDF publishing tool designed for clean Persian, English, and mixed-language documents.

The project converts single Markdown documents or ordered multi-file books into print-ready PDF files with support for RTL/LTR direction handling, Persian-friendly typography, cover pages, tables of contents, PDF outline bookmarks, deterministic figure/table/equation/listing numbering, semantic cross-references, generated reference lists, offline BibTeX/CSL JSON citations and bibliographies, GitHub-style Markdown features, MathJax formulas, enhanced syntax-highlighted code, offline Mermaid flowchart-subset diagrams, local images, footnotes, callouts, safe HTML, watermarks, and a clean appearance system built around styles, palettes, and light/dark modes.

The main goal of the project is to make technical Markdown documents publishable as polished PDF outputs without forcing the author to leave the Markdown workflow.

```text
Markdown -> Structured HTML -> Chromium PDF
```

![Mardas MD2PDF](./README.png)

## Architecture

The system is organized around a browser-based rendering pipeline. Markdown is first parsed and normalized, then converted into a complete HTML document with appearance CSS, cover metadata, table of contents, MathJax configuration, and print rules. Finally, Playwright controls Chromium to generate the final PDF.

### Markdown Processing

The Markdown layer also normalizes visual captions for images, tables, code listings, and Mermaid diagrams so the PDF layer can keep each caption with its associated print block. The reference engine assigns stable numbers and destinations to labeled objects, resolves semantic references before bidi isolation, and can generate lists of figures, tables, equations, and listings. The citation engine loads bounded local BibTeX or CSL JSON sources, resolves author-date or numeric citations after book assembly, and generates one linked bibliography without network metadata lookup.

The Markdown layer handles front matter, heading collection, table of contents and PDF outline generation, GitHub-style task lists, alerts, autolinks, heading anchors, image captions, enhanced code blocks with titles, line numbers, line highlights, and line-start metadata, Mermaid flowchart-subset diagrams, extended callouts, footnotes, safe HTML, local image embedding with blocked placeholders, print-fit wide tables, math protection, and direction-aware document metadata.

### PDF Rendering

Print-flow rules now keep headings with their first block, protect ordinary paragraphs from orphan/widow lines, and let long code blocks or large tables split only when avoiding the split would waste page space.

PDF navigation is kept consistent across both navigation layers: the visible table of contents and the PDF viewer outline/bookmarks both jump to the same real heading destinations after metadata writing and cover/content merging.

The renderer builds the final printable HTML, validates page size and margin options, applies the selected style, palette, and mode, renders MathJax when enabled, separates the cover from numbered content pages, applies mode-aware watermark overlays, writes PDF metadata and bookmarks, adds stable page labels and running footers, and exports the result through Chromium.

### Interfaces

The project provides three supported process interfaces:

- `mrs-md2pdf` for command-line and automation workflows.
- `mrs-md2pdf-gui` for the current local browser-based Studio during the desktop migration.
- `mrs-md2pdf-sidecar` for native desktop clients. It exposes a versioned JSON-RPC protocol over standard streams, opens no localhost port, reports progress, and supports cooperative cancellation.

The target product architecture keeps the Python publishing engine and places a native desktop shell around the sidecar. Architecture decisions and the protocol contract are documented under [`docs/architecture/`](./docs/architecture/).

## Documentation

The README is intentionally short. Mardas MD2PDF uses a **guide-first documentation model**:

- [English Guide](./docs/guides/GUIDE.en.md) — the complete English user manual and live rendering sample.
- [راهنمای فارسی](./docs/guides/GUIDE.fa.md) — the complete Persian/RTL user manual and live rendering sample.
- [Documentation map](./docs/README.md) — the small index for release, maintenance, security, and documentation policy files.

Generated PDF versions of the guides are available in the [`examples/`](./examples/) directory. Feature documentation is not split across parallel reference pages; user-facing explanations, runnable examples, and renderer smoke cases belong in the guides so the Markdown source and the official PDFs stay synchronized.

Release and operations references are [Changelog](./docs/CHANGELOG.md), [Release checklist](./docs/RELEASE.md), [Maintenance workflow](./docs/MAINTENANCE.md), [Security policy](./docs/SECURITY.md), and [Documentation policy](./docs/DOCUMENTATION.md).

## Standalone Runtime Foundation

Version 1.23.0 adds the first self-contained desktop-engine artifact. The Windows release workflow builds a portable `onedir` runtime containing Python, Mardas MD2PDF, Playwright resources, and the pinned Chromium headless shell. A user of that runtime does not install Python, pip, Node.js, Git, or Chrome.

This artifact is the engine foundation for the native desktop application; it is not yet the redesigned Tauri GUI. The existing `mrs-md2pdf-gui` remains available while the native shell is developed.

Build the portable runtime on the target operating system:

```bash
python -m pip install -e '.[desktop]'
python -m playwright install chromium --only-shell
python scripts/build_standalone_runtime.py --clean
```

Verify the frozen executable, internal SHA-256 manifest, bundled browser, JSON-RPC lifecycle, and a Unicode-path PDF render:

```bash
python scripts/verify_standalone_runtime.py \
  build/standalone-runtime/Mardas-MD2PDF-1.23.0-runtime-windows-x86_64 \
  --render
```

The sidecar can also be exercised from a Python installation:

```bash
mrs-md2pdf-sidecar --health
mrs-md2pdf-sidecar --capabilities
```

Do not write logs or human-readable status to sidecar `stdout`; JSON-RPC messages use `stdout` and operational logs use `stderr`.

## Quick Start

```bash
git clone https://github.com/mragetsars/Mardas-MD2PDF.git
cd Mardas-MD2PDF
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

Render a PDF:

```bash
mrs-md2pdf input.md -o output.pdf --toc --style modern --palette emerald --mode light
```

For thesis, journal, and release artifacts, enable the strict publication profile. It fails instead of silently degrading when MathJax remains unresolved, a required font is unavailable, or PDF navigation cannot be preserved. The JSON report records browser font evidence, MathJax counts, navigation reconstruction, and the final render result:

```bash
mrs-md2pdf input.md -o output.pdf \
  --quality-profile strict-publication \
  --require-font Vazirmatn \
  --quality-report build/output-quality.json
```

The standard profile remains backward compatible and reports these conditions as warnings. Override one category with `--math-error-policy`, `--font-error-policy`, or `--navigation-error-policy`. Mardas MD2PDF does not redistribute font binaries; install the required families locally or point `--font-dir` to trusted font files.

Create a reusable project configuration and validate it without opening Chromium:

```bash
mrs-md2pdf init
mrs-md2pdf validate input.md
mrs-md2pdf explain-config input.md
mrs-md2pdf doctor input.md
```

The nearest `mardas.toml` is discovered from the document directory upward. Command-line options override project values, which override equivalent front-matter values. Use `--config`, `--no-config`, and `--format json` for explicit automation workflows.

Create and build an ordered multi-file book:

```bash
mrs-md2pdf init my-book --book
mrs-md2pdf validate-book my-book
mrs-md2pdf explain-book my-book
mrs-md2pdf build-book my-book
```

Book Mode keeps chapter order in `[book].chapters`, namespaces heading and footnote IDs, embeds chapter-local or shared project-root assets, restores links between listed chapters, and produces one TOC, outline, cover, metadata set, and PDF artifact.

Enable semantic numbering and cross-references in a single document or book:

```toml
[references]
enabled = true
numbering_scope = "chapter"
list_of_figures = true
list_of_tables = true
```

```markdown
See @fig:architecture and @tbl:metrics.

![Architecture](assets/architecture.svg)

*Figure. Processing architecture.* {#fig:architecture}

| Metric | Value |
| :--- | ---: |
| Accuracy | 0.98 |

Table: Evaluation metrics {#tbl:metrics}
```

The supported semantic object prefixes are `fig`, `tbl`, `eq`, and `lst`. Labels are unique across the complete rendered document, including all chapters in Book Mode.

Enable an offline project bibliography:

```toml
[bibliography]
enabled = true
sources = ["references.bib"]
style = "author-date"
include_uncited = false
```

```markdown
Prior work supports the result [@doe2024, p. 12].
Narrative form: @smith2023 describes the method.
```

The built-in styles are `author-date` and `numeric`. Sources remain local to the project, Book Mode produces one bibliography for all chapters, and builds never perform DOI lookup or metadata downloads.

Cover branding is off by default so exported PDFs belong to the document owner. Enable explicit branding only when desired:

```bash
mrs-md2pdf input.md -o output.pdf --branding full --brand-name "Acme Research Lab"
```

Explore appearance choices:

```bash
mrs-md2pdf --list-styles
mrs-md2pdf --list-palettes
mrs-md2pdf --list-modes
```

Launch the GUI for an independent document:

```bash
mrs-md2pdf-gui
```

Open a real `mardas.toml` project workspace:

```bash
mrs-md2pdf-gui --project path/to/project
```

Project Workspace mode adds a project file tree, Book Mode chapter badges, a Problems panel backed by the same structured diagnostics as the CLI, safe file opening/saving, renderer-backed preview for the active Markdown file, and full-book preview/export. Problem entries navigate to the responsible project file and line. Saves use content hashes and atomic replacement, so Studio rejects stale edits when a file changes externally.

Studio exports run through a bounded queue. Publication Quality exposes the same strict profile, category policies, and required-font checks as the CLI; completed jobs return a bounded quality summary to the footer. The footer reports the real renderer stage, queue wait, and completion percentage; an active or queued export can be cancelled without terminating unrelated jobs. Chromium is reused by a dedicated worker only across trusted local exports, while every document receives a fresh browser context. Tune the local queue when needed:

```bash
mrs-md2pdf-gui --render-workers 2 --export-queue-size 6 --render-idle-timeout 60
```

Measure the same deterministic performance profiles before and after renderer changes:

```bash
python scripts/benchmark_large_documents.py \
  --profiles small,pages50,pages250,editor-loop \
  --mode both \
  --repeats 3 \
  --output-dir build/performance
```


Audit source accessibility before rendering and inspect the final PDF without making unverified standards claims:

```bash
mrs-md2pdf audit-accessibility report.md
mrs-md2pdf audit-book-accessibility path/to/book
mrs-md2pdf audit-pdf dist/book.pdf --profile all
```

Source audits check declared language, heading hierarchy, image alternative text, link names, table headers/captions, and the selected theme's text contrast. PDF audits inspect catalog language, XMP metadata, font embedding, ToUnicode maps, tagging signals, JavaScript, attachments, output intents, and PDF/A identifiers. JSON output and `--fail-on error|warning|never` make the commands suitable for CI. These are readiness checks: Mardas MD2PDF does **not** claim PDF/UA or PDF/A conformance without an independent standards validator.

## Release Verification and Offline Bundles

Tagged release workflows verify the project on Linux, Windows, and macOS, build deterministic wheel/source artifacts, generate an SPDX 2.3 runtime SBOM, and create platform-specific offline Python wheel bundles. The bundles contain the project wheel and resolved runtime dependency wheels, but deliberately do not claim to include Chromium or a standalone Python runtime.

Verify a downloaded release directory before installing:

```bash
sha256sum -c CHECKSUMS.sha256
python scripts/finalize_release_artifacts.py \
  --artifact-dir . \
  --version X.Y.Z \
  --require-sbom \
  --verify-only
```

Official GitHub artifacts can also be verified against their signed provenance:

```bash
gh attestation verify mardas_md2pdf-X.Y.Z-py3-none-any.whl \
  --repo mragetsars/Mardas-MD2PDF
```

An offline Python bundle is installed from its extracted directory:

```bash
python install.py --target mardas-md2pdf-venv
```

The installer verifies the embedded checksums and invokes pip with `--no-index`. PDF rendering still requires a compatible Chromium executable; the optional `python -m playwright install chromium` step may require network access.

The Studio interface groups export settings into Document, Appearance, Branding, Layout, Publication Quality, and Advanced sections. Appearance and branding choices use visual cards, while advanced controls such as watermarks and local assets stay collapsed until needed. The **Open Bundle** and **Save Bundle** controls handle portable `.mardas.json` snapshots containing Markdown, export options, and attached assets; they are separate from the live on-disk Project Workspace opened with `--project`. Studio also supports drag-and-drop asset management, auto-scaling PDF-like renderer-backed preview, Fast approximate browser-local preview, debug HTML export, and a command palette via **Ctrl/Cmd+K**. In Project Workspace mode, **Ctrl/Cmd+S** saves the active project file; **Ctrl/Cmd+Shift+S** saves a portable bundle, and **Ctrl/Cmd+Enter** exports the normal single-document PDF. The complete Studio walkthrough lives in the guides.

## Repository Structure

The project is organized as follows:

```text
Mardas-MD2PDF/
├── src/mardas_md2pdf/      # Python package source
│   ├── markdown.py         # Markdown parsing, front matter, TOC, math, Mermaid, footnotes, safe HTML
│   ├── mermaid.py          # Offline Mermaid flowchart-subset-to-SVG renderer
│   ├── renderer.py         # HTML assembly, appearance CSS, MathJax, Chromium PDF rendering
│   ├── quality.py          # Strict publication policies and structured render-quality evidence
│   ├── pdf_navigation.py   # Public-API PDF destinations, links, outlines, and page labels
│   ├── references.py       # Numbered objects, semantic labels, cross-references, and generated lists
│   ├── citations.py        # Offline BibTeX/CSL JSON parsing, citation resolution, and bibliography output
│   ├── book.py             # Ordered chapter manifest, namespacing, cross-links, and book assembly
│   ├── application.py      # Stable application API shared by desktop-sidecar operations
│   ├── protocol.py         # Versioned JSON-RPC envelope and error contract
│   ├── runtime.py          # Frozen-runtime and bundled-Chromium discovery
│   ├── sidecar.py          # Stdio JSON-RPC process for native desktop clients
│   ├── cli.py              # Conversion command-line interface
│   ├── config.py           # Versioned mardas.toml discovery, validation, and resolution
│   ├── diagnostics.py      # Stable text/JSON diagnostic records
│   ├── project_commands.py # Project diagnostics plus init/build/validate/explain Book Mode workflows
│   ├── workspace.py        # Safe Studio project tree, file I/O, diagnostics, preview, and Book export
│   ├── render_pool.py      # Bounded export workers with thread-affine reusable Chromium sessions
│   ├── studio_jobs.py      # Disk-backed Studio export jobs, progress, cancellation, and retention
│   ├── gui.py              # Local browser-based GUI backend
│   └── assets/             # Style CSS, GUI shell, logo, and vendored MathJax files
├── docs/                   # Guides, architecture decisions, release, security, and documentation policy
│   └── guides/             # Complete English and Persian user guides
├── examples/               # Generated PDF examples from the guide files
├── packaging/              # PyInstaller entrypoint and onedir runtime specification
├── schemas/                # Versioned sidecar JSON-RPC schemas
├── scripts/                # Checks, distributions, frozen-runtime builds, visual QA, and cleanup
├── tests/                  # Automated pytest test suite
├── pyproject.toml          # Package metadata and dependencies
├── .github/workflows/      # CI and release artifact automation
├── LICENSE                 # MIT license
└── README.md               # Project introduction
```

## Examples

The `examples/` directory contains generated PDF outputs of the guide files:

```text
examples/
├── GUIDE.en.pdf
└── GUIDE.fa.pdf
```

These files are intended to show the real PDF output produced by the current documentation. They are also used as release-facing print samples during typography and media audits.


## Security Model

Mardas MD2PDF is intended for local publishing workflows. Local Markdown images and all front-matter branding logos are resolved relative to the Markdown document, restricted to regular supported image files inside that document root, and embedded before Chromium renders the PDF. Out-of-bound paths, symlink escapes, unsupported files, and oversized images are rejected or rendered as visible blocked placeholders. Relative filesystem links remain readable text but are not exported as machine-local `file:` annotations.
Bibliography sources are bounded local `.bib` or CSL `.json` files resolved inside the document/project root; citation rendering performs no network lookup and accepts only validated internal citation keys.

Remote `http(s)` images are blocked by default for privacy; use `--allow-remote-assets` only for trusted documents that intentionally fetch network images. Studio Fast Preview follows the same privacy boundary: it does not fetch remote or local image paths, and it disables unsafe or filesystem link schemes. Raw HTML is sanitized unless `--unsafe-html` is used, and safe `data:` image URLs are limited to common raster formats.

Chromium sandboxing is configurable with `--chromium-sandbox auto|on|off`; the default `auto` keeps sandboxing enabled for normal users and disables it only when running as root in container-style environments. Output PDF and debug HTML files are committed atomically, and the CLI rejects input/output/debug paths that resolve to the same file. Reference labels are document-internal identifiers only: they do not expand filesystem access, enable scripts, or bypass the existing asset and HTML trust boundaries. See [docs/SECURITY.md](./docs/SECURITY.md) for the full trust boundary.

## Testing

```bash
pip install -e .[dev]
./scripts/check.sh
python -m pytest -q tests/test_cross_references.py tests/test_book_mode.py
python scripts/benchmark_large_documents.py --profiles small,editor-loop --mode both --repeats 2
```

Clean local build and patch artifacts when the working tree starts to feel noisy:

```bash
./scripts/clean_workspace.sh
./scripts/clean_workspace.sh --patches  # also remove a temporary root-level patches/ directory
```


The official guide PDFs also exercise document-local image embedding with semantic figure captions and safe HTML image sizing.

The release workflow runs the consolidated release gate before publishing artifacts. It rebuilds and preflights the English and Persian guide PDFs, performs visual QA, installs the wheel in a clean environment, verifies packaged assets and entry points, builds and smoke-tests the Windows standalone sidecar runtime with pinned Chromium, and emits checksums for deterministic distributions and runtime archives.

The test suite covers Markdown transformation, GitHub-style features, direction handling, table of contents and outline generation, enhanced code highlighting, code-fence metadata, Mermaid SVG rendering, MathJax preservation, extended callouts, safe HTML, footnotes, local and remote image boundaries, renderer options, GUI availability, Studio option validation, page-size handling, wide-table print fitting, workspace persistence, deterministic example metadata, appearance validation, and fallback warnings. For visual changes to styles, palettes, or light/dark mode, run `python scripts/audit_appearance_matrix.py --output-dir build/appearance-audit --render-png --resume` and inspect the generated matrix. CI also runs `scripts/check_visual_contracts.py` to reject incomplete manifests, blank or implausibly small rasters, and broken Studio interaction contracts without depending on machine-specific PNG hashes. For complete chunked coverage across every style, palette, and mode plus the feature-heavy sample, run `python scripts/run_visual_qa_matrix.py --output-dir build/visual-qa/full --render-png --resume`; the summary file records active-chunk heartbeat data and skipped completed chunks. For targeted feature-heavy coverage, run `python scripts/audit_pdf_features.py --all-appearances --render-png --resume`.

## Contributors

This project was developed and maintained by:

- **[Meraj Rastegar](https://github.com/mragetsars)**

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for details.
