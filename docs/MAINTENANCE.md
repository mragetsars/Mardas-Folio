# Maintenance Workflow

This document keeps routine project work predictable and patch-friendly.

## Local checks

Run the default quality gate before creating a patch or tag:

```bash
./scripts/check.sh
./scripts/check_critical_coverage.sh
python -m pytest -q tests/test_project_config.py tests/test_book_mode.py tests/test_cross_references.py
```

The script runs Ruff, the scoped Pyright contract, and pytest from the repository root. `check_critical_coverage.sh` separately enforces branch coverage on the publication-quality and PDF-navigation modules. It disables third-party pytest plugin autoload by default so local virtualenv plugins cannot change release-gate behavior; set `MARDAS_ALLOW_PYTEST_PLUGINS=1` only when intentionally debugging pytest plugins. To include real Chromium render smoke tests, including PDF metadata and outline inspection, enable the optional environment flag:

```bash
MARDAS_RENDER_SMOKE=1 ./scripts/check.sh
```

For slow CI runners, `MARDAS_TIMEOUT_MS` controls the Chromium page timeout and `MARDAS_RENDER_SMOKE_TIMEOUT` controls the outer smoke-command timeout:

```bash
MARDAS_RENDER_SMOKE=1 MARDAS_TIMEOUT_MS=600000 MARDAS_RENDER_SMOKE_TIMEOUT=420 ./scripts/check.sh
```

## Book Mode checks

Changes to the book manifest, chapter assembly, ID namespacing, shared asset resolution, or cross-chapter links require the focused suite:

```bash
python -m pytest -q tests/test_book_mode.py tests/test_pdf_toc_destinations.py
```

Before release, create a representative book with at least two chapters, duplicate heading text, a shared project-root image, and a link from one chapter to a heading in another. Verify the combined HTML contains no absolute machine paths and inspect the PDF TOC, outline, page breaks, named destinations, and link annotations. The consolidated release gate also builds the starter Book Mode project from the cleanly installed wheel.

## Cross-reference checks

Changes to semantic labels, caption normalization, reference localization, generated lists, Book Mode assembly, or PDF destination writing require the focused suite:

```bash
python -m pytest -q tests/test_cross_references.py tests/test_book_mode.py tests/test_pdf_toc_destinations.py
```

Before release, render a representative English/Persian book containing a labeled figure, table, display equation, and code listing. Verify global and chapter-scoped numbering, a reference that crosses chapter boundaries, duplicate/unresolved diagnostics, all requested generated lists, and the corresponding `xref-*` named destinations and link annotations in the PDF. Official guide builds also enable all four reference lists as live renderer samples.

## Bibliography and citation checks

When changing `src/mardas_md2pdf/citations.py`, bibliography configuration, or Book Mode citation assembly, run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_citations.py \
  tests/test_book_mode.py \
  tests/test_project_config.py \
  tests/test_security_boundaries.py \
  tests/test_documentation_integrity.py
```

Also rebuild both guides. They load `docs/guides/GUIDE.references.bib` as a live offline source and must produce author-year disambiguation, narrative/grouped citation links, one generated bibliography, and stable `/bib-*` PDF destinations. No release check may require DOI lookup or network metadata retrieval.

## Studio Project Workspace checks

Changes to `src/mardas_md2pdf/workspace.py`, project API routes, Project Explorer, Problems Panel, safe file saving, or Book preview/export require:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_studio_project_workspace.py \
  tests/test_gui_assets.py \
  tests/test_studio_sidebar_layout.py \
  tests/test_visual_qa_scripts.py
```

Run both the ordinary Studio browser audit and the project-aware audit against a representative Book Mode project:

```bash
python scripts/audit_studio_visual.py --output-dir build/studio-audit --clean
python scripts/audit_studio_visual.py \
  --project path/to/book-project \
  --output-dir build/studio-project-audit \
  --clean
```

Verify project-relative diagnostics, safe navigation to a chapter line, external-change conflict handling, UTF-8/size boundaries, project-root and symlink rejection, renderer-backed active-file preview, and saved full-book preview/export. The installed-wheel release gate also imports `mardas_md2pdf.workspace`, performs a hash-guarded atomic save, checks `mrs-md2pdf-gui --help` for `--project`, and captures a Chromium project-workspace audit.

## Performance and large-document checks

Performance changes require a before/after benchmark using the same source tree, Chromium executable, Python version, machine load, profile set, repeat count, and timeout. Run the deterministic helper from the repository root:

```bash
python scripts/benchmark_large_documents.py \
  --profiles small,pages50,pages250,pages500,editor-loop \
  --mode both \
  --repeats 3 \
  --timeout-ms 300000 \
  --output-dir build/performance \
  --output build/performance/report.json
```

The `cold` mode starts Chromium for every conversion. The `session` mode reuses one Chromium process while creating a fresh browser context for every repeat. Compare wall-clock distributions, page counts, PDF sizes, browser-launch counts, and peak RSS; do not claim an optimization from one run or from different input profiles.

For targeted reliability checks:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_performance_reliability.py \
  tests/test_studio_export_jobs.py \
  tests/test_performance_benchmark.py

MARDAS_RENDER_SMOKE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -m pytest -q tests/test_performance_reliability.py
```

Verify that Studio returns `429 export_queue_full` when the bounded queue is exhausted, queued cancellation prevents work from starting, running cancellation is reported as cooperative, completed PDFs are streamed from disk, and an idle worker closes its reusable browser after the configured timeout.

## Generated examples

The guide PDFs in `examples/` are generated artifacts that should match the current Markdown guides. The helper sets a default `SOURCE_DATE_EPOCH` so PDF metadata dates stay deterministic across repeat builds. Regenerate them with:

```bash
./scripts/build_examples.sh
```

Override `SOURCE_DATE_EPOCH` only when a release intentionally needs a different deterministic metadata date. Use `MARDAS_TIMEOUT_MS` when CI or a slow local machine needs a longer browser timeout:

```bash
MARDAS_TIMEOUT_MS=240000 ./scripts/build_examples.sh
```


## Publication-quality diagnostics

Renderer, MathJax, font, or PDF-navigation changes require a strict smoke artifact and its structured report:

```bash
mrs-md2pdf docs/guides/GUIDE.en.md \
  -o build/quality-smoke.pdf \
  --quality-profile strict-publication \
  --require-font Vazirmatn \
  --quality-report build/quality-smoke.json
```

Do not override a strict failure merely to make a release pass. Confirm that each report has no error event, that MathJax detected/rendered counts match, and that named destinations and internal links are preserved. Font binaries remain external dependencies and must not be committed or included in patch bundles.

## Appearance matrix audit

When changing `src/mardas_md2pdf/appearance.py` or any `src/mardas_md2pdf/assets/style-*.css` file, render
every built-in style, palette, and mode combination before shipping the patch:

```bash
python scripts/audit_appearance_matrix.py --output-dir build/appearance-audit --render-png --resume
```

After artifact generation, run `scripts/check_visual_contracts.py` against the appearance, feature, and Studio manifests. Review the cover and content PNGs for contrast, palette accents, code blocks,
callouts, tables, formulas, and dark-mode background consistency. This audit is
intentionally not part of the default CI path because it launches Chromium for
every combination.

For the complete style/palette/mode and feature-heavy matrix, use the chunked
runner. It skips already completed child manifests when `--resume` is set and
writes active-chunk heartbeat data to `summary.json` while long chunks run:

```bash
python scripts/run_visual_qa_matrix.py --output-dir build/visual-qa/full --render-png --resume
```

## Python distributions

Build wheel and source distribution artifacts with:

```bash
./scripts/build_dist.sh
```

The script removes the previous `dist/` directory before building so stale packages do not get uploaded by mistake. It derives `SOURCE_DATE_EPOCH` from the current commit when possible, fixes locale/timezone-sensitive build inputs, and normalizes the source archive so repeated wheel and sdist builds from the same tree are byte-identical.

## Release artifacts workflow

The `Release Artifacts` GitHub Actions workflow runs on `v*` tags and manual dispatch. It invokes `scripts/release_gate.sh` as the single release contract, including Chromium smoke, guide rebuild and PDF preflight, Visual QA, deterministic distribution builds, clean-wheel installation, packaged-asset and entry-point verification, SPDX SBOM generation, release-manifest validation, and checksum generation.

After the core artifacts pass, Linux, Windows, and macOS runners each resolve a platform-specific offline wheelhouse and build a deterministic offline Python bundle with `scripts/build_offline_bundle.py`. A final Linux job combines the core files, guide PDFs, and offline bundles, revalidates the complete manifest, then creates SLSA provenance and SBOM attestations through GitHub's OIDC/Sigstore service.

Useful local commands:

```bash
python scripts/generate_sbom.py --help
python scripts/build_offline_bundle.py --help
python scripts/finalize_release_artifacts.py --help
```

`CHECKSUMS.sha256` covers every file in the manifest-governed `release-X.Y.Z` artifact plus `RELEASE-MANIFEST.json`, but never includes itself. Signed Sigstore bundles are uploaded separately as `release-attestations-X.Y.Z` with their own checksum inventory, because attestations are created only after the release payload has been finalized. Offline bundles contain another checksum inventory for their internal files. Chromium is intentionally excluded from the offline bundle and must be provided separately.

## Standalone sidecar runtime

The standalone runtime is a target-platform artifact. Install the optional desktop build dependency, install the pinned Playwright Chromium headless shell, then build and verify the `onedir` runtime:

```bash
python -m pip install -e '.[desktop]'
python -m playwright install chromium --only-shell
python scripts/build_standalone_runtime.py --clean
python scripts/verify_standalone_runtime.py \
  build/standalone-runtime/Mardas-MD2PDF-X.Y.Z-runtime-<platform>-<arch> \
  --render
```

The schema-v2 verifier checks every regular-file digest and declared relative symlink target before launching the frozen sidecar. It rejects escapes, dangling links, cycles, traversal through links, and inventory mismatches; legacy schema-v1 manifests may contain regular files only. Release artifacts must include Chromium; `--allow-missing-chromium` is only for protocol/build diagnostics. Build each platform runtime on that platform because PyInstaller is not a cross-compiler.

## Patch set hygiene

Keep generated patch sets easy to apply:

1. Make one logical change per commit.
2. Keep commit subjects in the existing conventional style: `feat:`, `fix:`, `docs:`, or `chore:`.
3. Run `./scripts/check.sh` before formatting patches.
4. Regenerate `examples/*.pdf` only in a dedicated `docs: refresh guide PDF examples` commit.
5. Keep binary outputs out of normal code commits unless the commit is explicitly about generated assets.


## Workspace cleanup

Generated artifacts should not live in the repository root. Use the cleanup helper
when local test runs, editable installs, or patch application leave cache/build files
behind:

```bash
./scripts/clean_workspace.sh
./scripts/clean_workspace.sh --patches
```

The default cleanup removes Python caches, pytest/ruff caches, build outputs,
editable-install metadata, and the common root-level `output.pdf` scratch file.
The `--patches` option also removes a temporary root-level `patches/` directory
after patch sets have been applied.

## Release gate

Run `./scripts/security_audit.sh` to record installed dependency vulnerabilities, then run `./scripts/release_gate.sh` before tagging a release. The gate installs the newly built wheel into a fresh virtual environment, verifies both console entry points and required packaged assets, and writes `dist/CHECKSUMS.sha256`. Set `MARDAS_RELEASE_VISUAL_QA=1` when the full chunked visual matrix is required instead of the reduced smoke matrix.

## Accessibility and archival-readiness checks

Changes to Markdown semantics, captions, tables, images, link processing, language metadata, PDF post-processing, fonts, or document metadata require:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_accessibility_audit.py \
  tests/test_pdf_accessibility_audit.py \
  tests/test_markdown.py \
  tests/test_pdf_output.py

mrs-md2pdf audit-accessibility docs/guides/GUIDE.en.md --format json --fail-on error
mrs-md2pdf audit-accessibility docs/guides/GUIDE.fa.md --format json --fail-on error
mrs-md2pdf audit-pdf examples/GUIDE.en.pdf --profile all --format json --fail-on never
mrs-md2pdf audit-pdf examples/GUIDE.fa.pdf --profile all --format json --fail-on never
```

Review source diagnostics for language, heading order, alternative text, link purpose, table headers/captions, and palette contrast. Review PDF metrics for `/Lang`, XMP, font embedding, ToUnicode, tagging, output intents, JavaScript, and attachments. Do not convert the absence of a structure tree or PDF/A identifier into a passing result by adding unsupported catalog flags. Independent PDF/UA/PDF/A validation remains outside the built-in audit.

## Native desktop maintenance

The native application is split into `apps/desktop/frontend/` and `apps/desktop/src-tauri/`. Install the locked build dependencies, prove the committed CodeMirror 6 bundle is reproducible, then build and verify the fully offline frontend:

```bash
npm --prefix apps/desktop ci --no-audit --no-fund
npm --prefix apps/desktop run check:editor
python scripts/build_desktop_frontend.py
python scripts/verify_desktop_frontend.py apps/desktop/dist
node --test apps/desktop/tests/*.test.mjs
python -m pytest -q tests/test_desktop_app.py
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked
```

Rust is pinned by `apps/desktop/src-tauri/rust-toolchain.toml`; the committed `Cargo.lock` is part of the release input and native builders fail unless Cargo accepts it with `--locked`. Regenerate and review that lockfile only as an explicit dependency update. On Windows, stage only a runtime that passes its complete SHA-256 manifest and includes pinned Chromium. `scripts/build_desktop_app.py` performs frontend verification and runtime staging before invoking Tauri. Do not commit `apps/desktop/dist/`, Rust `target/`, or staged sidecar files. Regenerate checked-in application icons from the canonical SVG with `python scripts/generate_desktop_icons.py`.

Authoring changes must keep the document lifecycle tests green. In particular, verify atomic save, revision conflicts, unsaved-buffer preview/validation, symlink rejection for imported assets, bounded recovery/session storage, literal find/replace, and the static no-localhost/no-external-browser contracts. The top-level front-matter form intentionally edits only scalar fields; preserve unknown and nested YAML rather than trying to flatten it in the frontend.

## Cross-platform native desktop package checks

Native desktop changes require the target-platform builder and verifier:

```bash
python scripts/build_native_desktop.py --help
python scripts/verify_native_desktop.py --help
python -m pytest -q tests/test_native_desktop.py tests/test_release_provenance.py
```

The standalone sidecar runtime must be built on the same operating system as the native package. The commands above are required checks, not evidence that a particular Windows/macOS/Linux job has run. Linux release CI intentionally uses Ubuntu 22.04 as the compatibility baseline. Windows Setup embeds the WebView2 offline installer, while the portable ZIP expects a system WebView2 runtime. Signing and notarization evidence must come from the credentialed target-platform release run.

Support-bundle changes additionally require:

```bash
python -m pytest -q tests/test_support_bundle.py tests/test_sidecar_protocol.py
```

Do not add document paths, document contents, home paths, environment variables, tokens, or credentials to the support archive.

## Updater metadata checks

When updater signing keys are unavailable, update support is readiness-only. Validate the static manifest tool independently:

```bash
python -m pytest -q tests/test_update_manifest.py
python scripts/generate_update_manifest.py --help
```

Never commit `TAURI_SIGNING_PRIVATE_KEY` or its password. See `docs/UPDATES.md`.
