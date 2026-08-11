# Changelog

All notable changes to Mardas Folio are tracked here.

The project follows semantic versioning for user-visible behavior. Patch releases may include documentation, generated guide PDF refreshes, regression tests, and narrowly scoped renderer/Studio fixes.

## 2.0.0 - 2026-08-10

First release of the product under its own name. The desktop application is now
the primary interface, the export screen previews the actual PDF, and the
publishing engine's full option surface is reachable without editing a
configuration file by hand.

### Added
- Made the export preview show the PDF itself. The engine now composes the whole published page — cover, contents, body, bibliography, watermark, running footer, every stylesheet and the sheet geometry — and the export screen lays it out as real paper: correct page size, real margins, one sheet per page, a page count, zoom and margin guides. Page breaks follow the document's own break rules and land between lines, not through them, so "contents on its own page" and "every H1 starts a page" are visible before a file is written.
- Rebuilt the export settings as a browsable library: a category rail with per-category change counts, a search that covers option names and plain language, a one-sentence explanation of what every one of the 53 options decides, palette swatches in the colours the renderer prints, and inline validation of lengths and numbers before a render is started.
- Gave every boolean option a third state. A checkbox can only say on or off, so an unchecked box and an option the user never touched looked identical, and sending "off" for an option `mardas.toml` had turned on was a silent override.
- Gave the editor one command vocabulary. The toolbar, the keyboard, the command palette and the context menu now run the same commands, which toggle rather than only insert: pressing bold on bold text removes it, and applying a list to a list turns it back into paragraphs.
- Added the full editing keymap — headings 1–6 and back to paragraph, strikethrough, inline code, code block, the three list kinds, quote, table, rule, task toggle and paste-as-plain-text — bound inside the editor so they share its undo history.
- Added a heading menu that shows each level at its own weight, and a desktop-density right-click menu with copy, copy as HTML, copy as plain text, paste as plain text, insert image, validate, export and reveal.
- Added typewriter scrolling and a distraction-free focus mode, both opt-in, in Settings and the command palette.
- Rendered callouts, YAML front matter and fenced-code languages as what the engine publishes: `> [!WARNING]` becomes a coloured admonition card, front matter collapses to a metadata summary until the caret enters it, and a fence shows its language as a chip instead of its backticks.
- Completed the rename to **Mardas Folio**, identifiers included. The product is called that everywhere it is named — the interface and window title, the cover and brand block of every generated PDF, the `/Creator` and `/Producer` metadata written into the file, the browser GUI, the packaged stylesheets, the documentation and the guides — and so is every identifier other systems resolve the project by: the `mardas_folio` import package and `mardas-folio` distribution, whose commands are now `folio`, `folio-gui` and `folio-sidecar`; the `Mardas-Folio-*` release artifacts that the update endpoint and the attestation address; and the `io.github.mragetsars.mardas-folio` bundle identifier the updater and the per-user config directory are keyed by. All three moved while no published artifact and no installed client addressed the old ones, which is the only moment they are free: to an installed client a new bundle identifier is a different application, so after a release that one would have been a data migration rather than a rename. The packaged brand assets are named for the product too. A test fails if any spelling of the old name reappears anywhere but this changelog.
- Added a live preview editing mode: Markdown syntax marks are hidden and the formatting is rendered in place, while the line holding the caret shows its raw source so it stays editable. Tables, thematic rules, task checkboxes and local images render as real elements.
- Added a Write / Source / Split view control that replaces the separate "show source" and "show preview" toggles, and moved the formatting tools out of the window toolbar onto the document they act on.
- Exposed all 53 publishing-engine options in an Advanced settings panel grouped by concern, alongside a live preview of the document as the chosen options will publish it. Previously the interface sent nine and the rest needed a hand-edited `mardas.toml`.
- Added YAML front matter parsing to the editor, matching the engine's own rules, so document metadata is highlighted as metadata.

### Documentation
- Wrote down the updater key generation the release guide had only referred to. `docs/UPDATES.md` said to "run the Tauri key-generation command" without giving it, named neither file it writes, and did not say that the key blocks a `draft` release exactly as it blocks a `public` one — so an unsigned first release looked possible with no secrets at all, and would have stopped at the tag workflow's first job.
- Told users how to open a release that is not code-signed yet. The README described the packages without mentioning that Windows and macOS refuse to open them on a double-click, which is the point at which a first-time user gives up: SmartScreen needs **More info → Run anyway**, and Gatekeeper needs right-click **Open** rather than a double-click.

### Changed
- Renamed the repository to `Mardas-Folio` so the project, the product and the repository share one name. Three systems address it by that slug and were moved together: the update endpoint compiled into desktop binaries, the provenance and attestation repository, and the release artifact names. No release had been published, so no installed client was holding the previous endpoint.
- Rebuilt the interface around a strictly neutral grey scale with an orange accent, at desktop control density: no marketing hero, no drop shadows on static panels, ~30px controls and small radii.
- Replaced CodeMirror's `defaultHighlightStyle` with a purpose-built syntax theme driven by `--cm-*` custom properties, so light and dark are one code path.

### Fixed
- Brought `Cargo.lock` up to the released version. It still recorded the crate at `1.31.0`, so `cargo test --locked` — the first step of both native desktop jobs — refused to run at all. The failure was invisible because those jobs only start once the core matrix passes, and the core matrix was failing. The version bump checklist named six files and the lock was not one of them; it now names seven, and a test holds the locked entry against `__version__`.
- Pointed the desktop icon generator at the icon the desktop packages actually ship. The Folio application icon was added and rasterized into `apps/desktop/src-tauri/icons/`, but `generate_desktop_icons.py` and the packaged `PRODUCT_APP_ICON_SVG` still named the previous product's icon, so the next regeneration would have silently reverted the application icon to the old teal mark. The superseded icon is gone and a test holds the generator to the canonical one.
- Stopped the core test matrix failing on every operating system and Python version. `test_node_frontend_contracts` shells out to the desktop interface suite, several of whose tests import `@codemirror` and `@lezer` to drive the real parser — but that job never installs `node_modules`, so the imports could not resolve. It now skips when the dependencies are absent, and the `Native desktop contracts` job, which does install them, runs the suite for real.
- Pointed the pypdf compatibility matrix at the supported floor. It still pinned `4.0.0`, a version `pypdf>=6.15.0` refuses to install and which predates the `root_object` API the PDF audit uses, so the job only measured how far the matrix had drifted from the dependency floor raised for the pypdf advisories.
- Routed `preview.document_page` in the sidecar. Methods are declared in three places — what the engine advertises, what it implements, and what the JSON-RPC layer agrees to route — and the third was missed, so the desktop app was offered a method that then answered "Unknown method". A test now holds the routing table against the advertised list.
- Started the export preview when a source file is chosen. It previously waited for some unrelated option to be touched, so the panel sat on "choose a source file" after one had been chosen.
- Made the export preview stand down gracefully on an engine older than the interface: it asks what the engine supports, falls back to the body preview on assumed page geometry, and says so, instead of printing a protocol error into the panel.
- Repaired find-and-replace navigation in the professional editor. `currentEditor()` returns an adapter object, not an element, and passing it to `getComputedStyle` threw on every jump to a match.
- Restored arrowheads on Mermaid diagrams in the authoring preview. Preview ids are prefixed to avoid colliding with the application's own, but `marker-end="url(#…)"` was left pointing at the unprefixed id.
- Translated the export preview, the view switcher and the formatting tools into Persian. Those strings had only ever been added to the English table, so the primary interface language fell back to English for all of them.
- Stopped the preview losing the engine's palette, dark mode, fonts and page-break rules. The stylesheets declare their type scale on `:root` and key appearance and breaks off `body.md2pdf-…`, and neither selector can match inside a shadow root.
- Made the editor wrap long lines. A prose editor that scrolls sideways forces the reader to pan for every line; only fenced code keeps its own horizontal overflow.
- Removed the duplicated export controls. Page size, appearance, language and contents existed both in a "basic settings" strip and in the settings panel, so one value had two widgets that could disagree and precedence depended on merge order.
- Stopped the export preview competing with the export itself. The engine runs one job at a time and answers a second with SERVER_BUSY, so pressing Create PDF while a preview was rendering failed until retried; speculative preview work now yields.
- Moved the interface language into Settings, where it already existed, and removed the duplicate toggle from the title bar.
- Placed the caret on the line that was clicked. Heading lines carried their vertical spacing as margin and then as padding; CodeMirror maps a click through its own height map, and both put the box out of step with it, so every line below a heading was offset. The spacing now comes from line-height, which that map is built from.
- Made the export preview show the real published appearance by painting it with the engine's own style sheet, palette and body classes inside a shadow root, instead of generic Markdown.

### Fixed (earlier in this cycle)
- Made the editor parse GitHub-flavoured Markdown. `markdown()` defaults to CommonMark, so tables, task lists and strikethrough were never in the syntax tree even though the engine renders all three.
- Fixed dark-mode editor contrast: link and code-fence tokens sat at 1.35:1 and Markdown punctuation at 1.84:1 against the editing surface. Every interface text node now meets WCAG AA in both themes.
- Stopped the visually hidden switch inputs inheriting `input { width: 100% }`. Absolutely positioned with no positioned ancestor, that resolved against the viewport and produced a 1440px-wide invisible control that pushed the export view into horizontal scroll and swallowed clicks across a full-width strip.
- Stopped the document outline treating a `#` comment inside YAML front matter as a heading, which also misaligned preview-to-editor navigation.
- Pointed the support panel and export status surfaces at theme tokens instead of undefined custom properties, which had left them light-on-light in dark mode.

### Security
- Local images render through Tauri's asset protocol with an empty static scope, widened at runtime to the open document's own directory only, non-recursively. Remote sources and parent-directory escapes are refused in the interface as well.

## 1.31.0 - 2026-08-08

### Added
- Replaced the former desktop textarea with a deterministic, locally bundled CodeMirror 6 editor, including Markdown language support, commands, completion, diagnostics, native line numbers, offline third-party notices, and no CDN/runtime download.
- Extended the desktop engine API to 1.5.0 with `document.read_text` and `document.save_text` for bounded UTF-8 `.bib`, `.json`, `.toml`, `.txt`, `.yaml`, and `.yml` authoring files.
- Added runtime manifest schema v2 with explicit regular-file/symbolic-link entries and safe preservation of platform runtime links through build, staging, ZIP, verification, and release provenance.

### Changed
- Increased the bounded sidecar JSON-RPC request envelope to 64 MiB while retaining an independent 8 MiB UTF-8 limit for each editable document.
- Standardized document and project read/save responses around `kind`, `revision`, and `read_only` metadata; project responses also retain their SHA-256 conflict token and normalized paths.
- Made recovery scheduling and snapshots document-specific, serialized saves per document, and guarded preview, validation, asset, bibliography, project, and open-file results against stale asynchronous completion.
- Made non-Markdown project files use a focused plain-text authoring mode while keeping Markdown-only preview, formatting, front matter, citation, asset, and PDF actions unavailable where they do not apply.

### Fixed
- Routed project-backed saves through conflict-aware `project.save`, preserved edits made while an earlier save was in flight, and prevented a successful stale response from incorrectly marking newer content as saved.
- Prevented duplicate open requests and path aliases from creating multiple document models, and kept recovery/conflict state attached to the correct document across tab and project switches.
- Made literal find/replace Unicode-safe, corrected fenced-block parsing to match the opening fence character and length, and aligned Quick Export style, palette, and preset values with the engine contract.
- Rejected duplicate desktop JSON-RPC request IDs without replacing the original waiter; invalidated crashed/EOF sidecars with process-identity guards, disconnected pending requests promptly, restarted lazily, and reduced the desktop request timeout from one hour to ten minutes.
- Hardened keyboard tab navigation, command-palette active-descendant state, read-only editor behavior, and stale diagnostics/preview updates in the native workspace.
- Prevented duplicate Book actions from orphaning an active sidecar job, blocked Save As collisions with another open tab, retained diagnostics for the current path, and isolated full-book preview styles from the application shell.
- Rejected invalid UTF-8 surrogates in render options and returned stable document-read errors for missing directories, non-regular files, and operating-system read failures.
- Excluded the local desktop dependency tree from source distributions while retaining the locked editor source, deterministic bundle, package manifest, and third-party notices.
- Rejected invalid UTF-8 project-save content with a stable application error, required real Chromium inventory evidence in standalone runtimes, aligned nested runtime manifests and the 20,000-entry boundary, and moved release symlink checks ahead of path resolution.

### Security
- Validated every runtime path component before link dereference and rejected absolute or escaping symlink targets, dangling links, cycles, excessive chains, traversal through links, and manifest/filesystem type mismatches. Legacy schema-v1 manifests remain restricted to regular files.
- Hardened sidecar parsing and serialization for oversized requests, non-finite numbers, excessive integer digits, invalid response values, and supported-method/parameter boundaries.
- Validated all 53 renderer overrides against centralized type, range, enum, path, tuple, finite-number, nullability, and bounded-text contracts before normalization.
- Made dependency auditing inspect the exact non-editable installed closure without dependency resolution, fail on unexpected editable or direct-URL installs, and publish its report only after a successful strict audit.
- Pinned the Python build backend to security-fixed `setuptools` 83.0.0 and `wheel` 0.47.0 so isolated and pre-provisioned distribution builds use the same reviewed toolchain.

### Release
- Added explicit draft/public release modes, strict external credential validation, ephemeral Windows PFX and macOS keychain imports, explicit accepted-only DMG submission/stapling, native Authenticode/Developer ID/Gatekeeper/notarization verification, and artifact-bound evidence for one Windows, two macOS, and one Linux target.
- Committed the resolved Rust dependency graph, pinned native builds to Rust 1.97.1, required every Tauri runner to use `Cargo.lock` with `--locked`, and added locked Rust tests to the Windows/macOS/Linux CI matrix.
- Kept publication draft-only and credential-dependent. Source-level and portable tests do not claim that Windows Authenticode signing, macOS Developer ID signing/notarization, target-platform installer smoke, or public release publication completed; that evidence must come from the actual native release run.

### Tests
- Added backend and frontend contracts for supported text documents, project metadata and conflict saves, per-document recovery, save serialization, stale async guards, path identity, CodeMirror bundle integrity, Unicode find/replace, fence parsing, Quick Export values, sidecar lifecycle hardening, symlink-safe runtime manifests, renderer-option validation, and platform-signing evidence.
- Kept native packaging, signing, notarization, and clean-machine acceptance as target-runner/credential checks rather than representing them as completed by portable repository tests.

## 1.30.0 - 2026-08-08

### Added
- Added a native in-app update surface in Settings and the command palette. Update checking is manual, uses a bounded HTTPS endpoint, and remains disabled in builds that do not embed the maintainer-controlled updater public key.
- Added signed updater payload collection for Windows NSIS, Linux AppImage, and architecture-specific macOS updater archives, plus verified assembly of the multi-platform `latest.json` feed.
- Added release preflight checks that distinguish updater-signing requirements from production Windows/macOS code-signing and notarization readiness.
- Added version-scoped release-note extraction and a tag workflow stage that creates or refreshes a GitHub **Draft Release** from the fully verified release directory.

### Changed
- Pinned the Tauri updater Rust plugin to the verified `2.10.1` release because the desktop source tree does not currently commit a Cargo lockfile.
- Extended release provenance to classify updater signatures, macOS updater bundles, and `latest.json`, and optionally require exactly one verified update manifest.
- Hardened the tag workflow so signed updater metadata is assembled only after all required Windows, macOS, and Linux native jobs finish.
- Kept GitHub publication draft-only: the workflow refuses to overwrite an already-published release and never auto-publishes a tag.

### Security
- Kept `TAURI_SIGNING_PRIVATE_KEY` and its password outside source control; only the updater public key and HTTPS feed URL are embedded into signed release builds.
- Added validation that rejects updater endpoints using HTTP, embedded credentials, or URL fragments.
- Kept updater installation disabled by default in ordinary development builds and required a matching signed release version before installation.
- Kept production release publication blocked on real Windows code-signing and macOS Developer ID/notarization readiness; updater signatures do not substitute for operating-system trust.

### Fixed
- Corrected the frontend-to-Rust updater installation argument to use Tauri's default camelCase command payload convention, preventing an available update from failing at the install invocation boundary.

### Documentation
- Expanded release, distribution, and updater operations with signing-secret setup, draft-release review, and explicit public-release gates.

### Tests
- Added signed-update assembly, release preflight, release-note extraction, updater IPC, workflow, and native-updater artifact contracts.

## 1.29.0 - 2026-08-08

### Added
- Added a privacy-safe Support Bundle workflow to the native Help surface and command palette; the generated ZIP contains bounded product/runtime diagnostics while excluding document content, document paths, environment variables, and the user home path.
- Added normalized native artifact builders and verifiers for Windows Setup/portable ZIP, macOS DMG, Linux AppImage, and Linux Debian packages.
- Added signed static updater-manifest generation and verification tooling for future Tauri updater activation without committing updater private keys.
- Added platform-specific Tauri bundle configuration for Windows, macOS, and Linux, including a Windows WebView2 offline-installer strategy.

### Changed
- Extended the desktop engine API to 1.4.0 with the support-bundle operation.
- Hardened the release manifest so a complete native release can require Windows, macOS, and Linux coverage instead of accepting a Windows-only desktop artifact.
- Expanded CI and tag-release workflows to build and verify native desktop artifacts on Windows, Ubuntu 22.04, macOS ARM64, and macOS Intel runners.
- Added canonical macOS `.icns` and high-resolution PNG application icons generated from the existing project mark.

### Security
- Kept support diagnostics deliberately free of document contents, document paths, environment variables, and home-directory disclosure.
- Kept updater signing private keys outside source control and made signed HTTPS metadata a prerequisite for future automatic-update activation.

### Documentation
- Added native desktop distribution and updater-readiness operations guides.

### Tests
- Added support-bundle privacy, native artifact signature/inventory, multi-platform release-manifest, updater metadata, desktop UI, and workflow contract coverage.

## 1.28.0 - 2026-08-08

### Added
- Added a first-run desktop onboarding flow with document/book guidance, recovery and offline-safety explanations, restartable help, and local template-based document creation.
- Added local document templates, searchable Settings and Help surfaces, and a keyboard command palette without introducing runtime CDN dependencies.
- Added local interface preferences for system/light/dark appearance, content scale, reduced-motion behavior, automatic preview, and Persian/English UI language.

### Changed
- Made primary desktop actions discoverable from the top bar and command palette while keeping advanced publishing controls progressively disclosed.
- Localized editor status, runtime state, tooltips, icon-only control names, and new UX surfaces in both Persian and English.
- Improved responsive desktop layouts for the expanded authoring sidebar, templates, help, settings, and modal surfaces.

### Accessibility
- Added a skip-to-content link, visible keyboard focus treatment, accessible names for interactive controls, modal focus trapping and restoration, safe Escape handling, and ARIA live feedback.
- Added reduced-motion and enlarged-content preferences without changing document or PDF content.

### Tests
- Added deterministic preference, template, command-palette, modal-focus, desktop UX, and accessibility contracts.
- Added a structural accessibility audit to desktop CI and release gates, plus a browser-backed Chromium UX smoke in CI for onboarding, templates, settings, command navigation, and RTL behavior.

## 1.27.0 - 2026-08-06

### Added
- Added a native Book Project creation flow that generates a self-contained Unicode-safe project with `mardas.toml`, an initial chapter, shared assets and bibliography directories, and a deterministic PDF output path.
- Added chapter creation, duplication, ordering, drag-and-drop, and non-destructive removal from the configured book.
- Added whole-book validation, cancellable assembled-book preview, and native-path PDF export through the desktop Sidecar.
- Added a dedicated Book panel and Start Center entry points so ordinary users can complete the workflow without editing TOML or using the CLI.

### Changed
- Extended the desktop engine API to 1.3.0 and the versioned Sidecar method contract with the complete Book Project lifecycle.
- Made the request JSON Schema an exact tested mirror of the engine capability list.
- Preserved the existing Python Book Mode as the single implementation used by desktop validation, preview, and export.

### Security
- Guarded every chapter-list mutation with the SHA-256 revision of `mardas.toml` to prevent silent overwrite after an external project change.
- Bounded project titles, folder names, chapter count, chapter content, paths, and file allocation; rejected hidden, reserved, symbolic-link, traversal, and pre-existing project targets.
- Made chapter removal non-destructive: the file remains in the project and only its Book Mode entry is removed.

### Tests
- Added project creation, Unicode path, unsafe folder, symbolic-link, stale-config conflict, add, duplicate, reorder, remove, Sidecar contract, validation, preview, export, frontend API, drag-and-drop, and native UI coverage.

## 1.26.0 - 2026-08-06

### Added
- Added a native project-directory workflow with a bounded file tree, restored project sessions, Unicode-aware literal search, deliberately restricted regular-expression search, exact source-line result navigation, and cooperative cancellation.
- Added a searchable desktop bibliography index for configured local BibTeX and CSL JSON sources, cited/uncited status, parse diagnostics, and one-click citation insertion.
- Added trusted Markdown heading source maps to preview payloads and duplicate-safe bidirectional navigation between editor, outline, and preview.
- Added a stable editor adapter that decouples document, recovery, conflict, project, and preview state from the current editing widget.

### Changed
- Extended the desktop engine API to 1.2.0 with project open, refresh, read, conflict-aware save, search, and bibliography-index operations.
- Restored the active project with the document session and pruned hidden, generated, dependency, patch, and symlink directories before project enumeration.
- Replaced order-based preview heading linkage with backend-provided source-line metadata.

### Security
- Added project-root, supported-file, size, and symbolic-link boundaries to the new desktop project operations.
- Bounded project search query length, result count, line length, and file scope; rejected lookarounds, backreferences, quantified groups, and excessive repeats in interactive regular expressions.
- Preserved DOM sanitization and rejected out-of-project bibliography sources.

### Fixed
- Registered every new project and bibliography operation in the sidecar job allowlist so native UI requests no longer fail at the process boundary.
- Made the project-search action switch to an explicit cancel state while a search is running and exposed bounded-result truncation instead of silently hiding it.
- Prevented repeated bibliography refreshes from duplicating diagnostics in the Problems panel.

### Tests
- Added Markdown source-map, project traversal/search/cancellation, bibliography-index, sidecar allowlist, editor-adapter, project API, session restore, native-shell, and frontend workflow coverage.

## 1.25.0 - 2026-07-30

### Added
- Added a native multi-document authoring workspace with tabs, saved-session restore, bounded crash recovery, outline navigation, literal find/replace, formatting commands, top-level front-matter controls, assets, citations, diagnostics, and source-linked preview headings.
- Added versioned sidecar document operations for UTF-8 read, conflict-aware atomic save, asset discovery/import, and validation or preview of unsaved editor buffers.
- Added native multi-file open, Markdown Save As, and local asset pickers to the Tauri shell.

### Changed
- Extended the desktop engine API to 1.1.0 and moved recent-document opening into the authoring workspace while retaining the focused Quick Export workflow.
- Made the desktop preview explicitly recovery-safe: local recovery snapshots do not overwrite the source document, and external file changes require an explicit overwrite decision.

### Security
- Bounded document and asset sizes, rejected symbolic-link asset sources/directories, retained safe-HTML processing, and added defense-in-depth DOM sanitization for dirty-buffer previews.

### Tests
- Added application-service conflict, asset-boundary, sidecar authoring, frontend document/session/recovery, Markdown analysis, editor command, find/replace, and desktop contract coverage.

## 1.24.0 - 2026-07-30

### Added
- Added the first native Tauri 2 Mardas Folio shell with no external-browser launch or localhost server, native Markdown/PDF file dialogs, single-instance file forwarding, persisted window state, and `.md`/`.markdown` associations.
- Added a user-centered Start Center, recent documents, Quick Export presets, basic publication settings, validation, structured progress, cooperative cancellation, and open/reveal-output actions in Persian and English.
- Added deterministic frontend manifests, verified runtime staging, generated native icons, NSIS installer construction and verification, and a Windows desktop CI/release artifact.

### Changed
- Extended release manifests, checksums, attestations, and minimum release requirements with the versioned `Mardas-Folio-*-setup.exe` artifact.
- Kept the browser-based Studio available for advanced editing while establishing the native desktop application as the end-user distribution path.

### Security
- The native shell communicates with the frozen rendering engine only through bounded JSON-RPC standard streams, uses fixed native commands for opening local paths, and verifies the complete staged runtime before installer construction.

### Tests
- Added frontend unit contracts, atomic-build cleanup regression coverage, native-shell source/configuration contracts, runtime-staging tamper tests, installer PE/integrity validation, and Windows installer workflow assertions.

## 1.23.0 - 2026-07-30

### Added
- Added the versioned `mrs-md2pdf-sidecar` JSON-RPC 2.0 process interface over standard input/output with health, capability discovery, document/book render and validation operations, HTML preview, progress notifications, cooperative cancellation, busy-state protection, and controlled shutdown.
- Added a common application-service layer for desktop requests, strict option/parameter validation, project-configuration merging, structured engine errors, and bundled-runtime browser resolution.
- Added protocol v1 JSON schemas and accepted architecture decisions for product boundaries, stdio IPC, and the frozen runtime.
- Added PyInstaller `onedir` packaging, runtime SHA-256 manifests, portable ZIP generation, frozen-runtime verification, and a Windows CI/release job that renders a Unicode-path PDF without a system Python or Chrome dependency.

### Changed
- Extended release manifests and attestations with a separately classified, integrity-verified standalone runtime artifact.
- Added a `desktop` optional dependency group and the `mrs-md2pdf-sidecar` console entry point while preserving the existing CLI and browser-based Studio interfaces.

### Security
- Replaced the future desktop localhost boundary with a bounded line-oriented stdio contract, rejects unknown request fields, keeps logs off the protocol stream, limits request size, and verifies every file in a standalone runtime archive.

### Tests
- Added protocol parsing, configuration merge, runtime discovery, sidecar lifecycle, progress, cancellation, release-workflow, and standalone-runtime archive tamper tests.

## 1.22.0 - 2026-07-29

### Added
- Added `standard` and `strict-publication` quality profiles with independent `error`, `warn`, or `ignore` policies for MathJax completeness, required publication fonts, and PDF navigation preservation.
- Added bounded JSON render-quality reports containing MathJax detection/render counts, browser font evidence and local font-directory hashes, PDF destination/link reconstruction evidence, and final render status.
- Added Publication Quality controls to Studio, CLI-command export of those settings, and quality summaries on completed queued exports.
- Added semantic Visual QA contracts for appearance, feature-heavy PDF, and Studio manifests without committing machine-specific raster baselines.
- Added scoped Pyright, critical branch-coverage, dependency-audit, and minimum/latest `pypdf` compatibility gates.

### Changed
- Extracted PDF destination, link-annotation, outline, and page-label post-processing into `pdf_navigation.py` and replaced direct use of `PdfWriter._pages` and `PdfWriter._root_object` with public writer APIs.
- Changed generated project configuration so category policies inherit the selected quality profile unless explicitly overridden.
- Extended Studio visual auditing and release verification to require Publication Quality controls and semantic visual-contract reports.
- Made offline/pre-provisioned distribution builds fall back to the installed `setuptools.build_meta` backend when the PyPA `build` frontend is unavailable.

### Fixed
- Prevented MathJax failures and unresolved formula nodes from being silently accepted when strict publication output is requested.
- Recorded malformed, unmapped, out-of-range, or unresolvable PDF destinations and link annotations instead of silently discarding navigation failures.
- Made strict font requirements deterministic and explicit while preserving warning-based behavior for existing standard-profile users.
- Preserved source-distribution archive permissions while normalizing reproducible tar metadata, preventing normalized release archives from becoming owner-only files.

### Security
- Added an installed-environment `pip-audit` gate and retained bounded, path-safe quality-report handling in Studio temporary export storage.

### Tests
- Added policy, JSON-report, strict-font, unresolved-MathJax, navigation-failure, Studio quality-control, queued quality-summary, visual-contract, source-archive permission, and release-workflow regression coverage.

## 1.21.1 - 2026-07-29

### Fixed
- Declared generated XMP streams with the required PDF `/Type /Metadata` and `/Subtype /XML` entries so external PDF tools no longer report an unknown metadata-stream type.
- Made atomic PDF and debug-HTML output creation honor the process umask for new artifacts while preserving the mode of an existing destination during replacement.
- Synchronized Visual QA fixture cover versions with the installed package version instead of retaining historical hard-coded release numbers.

### Tests
- Added Chromium PDF regression coverage for XMP stream dictionaries and POSIX regression coverage for atomic-output permissions.
- Added release-integrity coverage that prevents Visual QA fixtures from drifting away from the package version.

## 1.21.0 - 2026-07-11

### Added
- Added cross-platform Linux, Windows, and macOS CI matrices with clean-wheel Unicode-path PDF rendering on every supported runner family.
- Added deterministic SPDX 2.3 runtime SBOM generation from a clean installed-wheel environment, including exact runtime dependency versions and release-artifact SHA-256 digests.
- Added validated `RELEASE-MANIFEST.json` and `CHECKSUMS.sha256` inventories plus platform-specific offline Python wheel bundles with self-verifying installers.
- Added scheduled CodeQL analysis and weekly Dependabot maintenance for Python and GitHub Actions dependencies.

### Changed
- Updated maintained GitHub Actions to their current Node 24-compatible major releases and separated core verification, platform wheel smoke, offline-bundle construction, and final attestation jobs.
- Extended the release gate to generate and verify the SBOM, release manifest, and checksums after clean-wheel installation.
- Defined offline distribution as a verified Python wheelhouse bundle rather than an unverified standalone executable; Chromium and a Python runtime remain explicit external prerequisites.

### Fixed
- Made the large-document benchmark importable on Windows and normalized macOS peak-RSS reporting to KiB.
- Canonicalized Studio export roots so resolved artifacts remain consistently related to their temporary root on macOS and other symlinked temporary directories.
- Made cross-platform path assertions and Windows absolute-path security fixtures portable without weakening the underlying boundary checks.

### Security
- Added OIDC/Sigstore-backed SLSA build-provenance and SPDX SBOM attestations for GitHub-hosted release artifacts without storing long-lived signing keys in the repository.
- Rejected release and bundle path traversal, symlink members, duplicate inventory entries, unlisted or missing files, unexpected versions, oversized artifacts, malformed SPDX data, and checksum mismatches.
- Kept offline installation index-free with checksum verification before virtual-environment creation and package installation.

### CI
- Added complete pytest coverage on Linux Python 3.10-3.13 and Windows/macOS Python 3.12-3.13, plus wheel-built Chromium rendering on all three operating systems.
- Added artifact retention, release-file aggregation, provenance attestation, and SBOM attestation to the tag/manual release workflow while retaining explicit maintainer control of GitHub Release publication.

### Tests
- Added release-provenance, deterministic SPDX, manifest/checksum, offline-bundle, archive-boundary, workflow-contract, and cross-platform smoke regression coverage.

### Notes
- GitHub attestations are created only by the hosted release workflow; local builds can generate and verify matching manifests, checksums, SBOM structure, and offline bundles but cannot reproduce GitHub's OIDC identity locally.
- Offline bundles include Python wheels only. A compatible Python interpreter and Chromium installation are still required for PDF rendering.

## 1.20.0 - 2026-07-11

### Added
- Added `audit-accessibility`, `audit-book-accessibility`, and `audit-pdf` commands with human-readable and JSON output plus configurable `--fail-on error|warning|never` release behavior.
- Added bounded source diagnostics for document language, heading hierarchy, image alternative text, link purpose, table headers/captions, and built-in theme contrast.
- Added PDF readiness inspection for catalog language, XMP metadata, font embedding, ToUnicode maps, tagging signals, JavaScript, attachments, output intents, encryption, and PDF/A identifiers.
- Added project-level `language` configuration and a `--lang` conversion override using validated BCP 47-style language tags.

### Changed
- Added catalog `/Lang`, viewer `DisplayDocTitle`, document information metadata, and XMP metadata to generated PDFs without adding unverified tagging or PDF/A conformance flags.
- Added deterministic figure/caption and table/caption relationships plus table-header `scope` attributes to rendered HTML where they can be derived safely.
- Improved the light emerald and amber palette accent colors to meet the built-in 4.5:1 normal-text contrast threshold.
- Extended the clean-wheel release gate to run source, Book Mode, and PDF readiness audits from the installed distribution.

### Fixed
- Classified Type 3 PDF fonts as embedded when their glyph programs are present in `/CharProcs`, avoiding false unembedded-font warnings in readiness reports.
- Kept exact code-listing and Mermaid markup stable while limiting new ARIA figure associations to image figures with explicit captions.
- Ignored literal inline-code examples and syntax-highlighting layout tables during source audits so accessibility diagnostics reflect real document semantics.

### Security
- Kept all accessibility and PDF audits local and bounded by the existing document, project, and file-size trust boundaries; no document content is sent to a network service.
- Kept compliance claims explicit and conservative: built-in audits do not claim WCAG, PDF/UA, or PDF/A conformance and never fabricate structure trees, output intents, or PDF/A identifiers.

### Tests
- Added source-audit, Book Mode audit, PDF-structure audit, language/XMP metadata, font-classification, semantic-HTML, palette-contrast, installed-wheel, and release-gate regression coverage.

### Notes
- Formal PDF/UA or PDF/A conformance still requires an independent validator and manual review; current Chromium output remains explicitly reported as unverified/untagged where applicable.

## 1.19.0 - 2026-07-10

### Added
- Added a thread-affine `RenderSession` that reuses one Chromium process across repeated exports while creating a fresh browser context for every document.
- Added a bounded Studio export queue with real stage progress, queue-wait/render timings, cooperative cancellation, retained disk-backed results, and explicit `429 export_queue_full` handling.
- Added `scripts/benchmark_large_documents.py` with deterministic small, 50-page, 250-page, 500-page, and editor-loop profiles for cold and persistent-session measurements.
- Added configurable Studio renderer controls: `--render-workers`, `--export-queue-size`, and `--render-idle-timeout`.

### Changed
- Studio PDF downloads are streamed from bounded temporary result files instead of loading complete large PDFs into server memory.
- Cached immutable packaged CSS, vendored MathJax, and bounded small local-image data URIs, and skipped full debug-HTML assembly when `--debug-html` is not requested.
- Preserved the legacy synchronous Studio render routes while routing them through the same bounded render pool used by the asynchronous job API.
- Extended the release gate and Chromium Studio audit to verify persistent-browser reuse, queued-export controls, packaged performance modules, and clean-wheel rendering.

### Security
- Kept each reused Chromium export isolated in a fresh browser context and restarted the browser after renderer failures or disconnection.
- Restricted completed export artifacts to regular files inside their assigned job directory, bounded result size and retention, and kept queue/job errors free of host paths and internal exceptions.
- Kept cancellation cooperative at documented renderer checkpoints rather than terminating shared worker processes unsafely.

### Performance
- Reduced measured mean wall time in the documented Linux benchmark environment by approximately 40% for the small profile, 21% for the 50-page profile, 37% for the editor-loop profile, 9% for the 250-page profile, and 11% for the 500-page profile when using a persistent render session; warm repeats improved by approximately 18-56% depending on profile.

### Tests
- Added render-session isolation/reuse, bounded-queue, cancellation, progress/timing, artifact-boundary, streamed-download, benchmark-contract, installed-wheel, Chromium-reuse, and Studio UI regression coverage.

## 1.18.0 - 2026-07-10

### Added
- Added `mrs-md2pdf-gui --project PATH` for opening a live `mardas.toml` Project Workspace with a project file tree, Book Mode chapter badges, active-file navigation, and saved full-book preview/export.
- Added a Problems Panel backed by the existing structured project, Book Mode, cross-reference, and citation diagnostics, including navigation to project-relative files and line/column locations.
- Added authenticated project GET/save/validate/preview/export API routes and renderer-backed preview for unsaved Markdown content using the actual project configuration, bibliography, references, and project-root assets.

### Changed
- Renamed the legacy `.mardas.json` toolbar actions to **Open Bundle** and **Save Bundle** so portable snapshots are clearly distinguished from a live on-disk Project Workspace.
- Extended the release gate and Chromium Studio audit to verify Project Workspace loading, project controls, installed-wheel workspace APIs, hash-guarded saving, and project-relative diagnostics.
- Preserved chapter source locations when Book Mode cross-reference or citation diagnostics are returned to Studio.

### Security
- Restricted editable workspace files to bounded UTF-8 text files inside the resolved project root, rejected hidden/generated paths and all symbolic-link traversal, and kept diagnostics free of absolute host paths.
- Added optimistic SHA-256 concurrency checks plus atomic, permission-preserving project-file replacement so external edits are never silently overwritten.
- Kept Project Workspace disabled unless Studio is explicitly launched with `--project`; all project APIs retain the per-run token and Host/Origin request boundary.

### Tests
- Added HTTP, path-boundary, symlink, external-change, file-size, invalid-encoding, atomic-save, Book preview, relative-diagnostic, DOM contract, installed-wheel, and Chromium visual regression coverage for Studio Project Workspace.

## 1.17.0 - 2026-07-10

### Added
- Added an offline-first bibliography and citation engine for local BibTeX and CSL JSON sources in single-file and multi-file Book Mode output.
- Added parenthetical and narrative citation syntax, built-in `author-date` and `numeric` styles, localized Persian/English punctuation and digits, stable PDF bibliography destinations, citation back-links, and optional uncited entries.
- Added `[bibliography]` project configuration, equivalent front-matter fields, and CLI overrides for sources, style, title, enablement, and uncited-entry behavior.

### Changed
- Resolved Book Mode citations only after all chapters are assembled so one first-use order and one bibliography are shared across the complete book.
- Extended clean-wheel release verification to render citations from an installed package and verify bibliography destinations in the generated PDF.
- Added deterministic same-author/same-year disambiguation with `a`, `b`, ... suffixes in both citations and bibliography entries.

### Security
- Kept bibliography processing local and offline, constrained configured sources to the document or project root, bounded source count, source size, and entry count, and protected source files from PDF/debug-output collisions.
- Rejected malformed sources, repeated source paths, duplicate bibliography keys, undefined citation keys, and malformed citation groups before Chromium starts.

### Tests
- Added BibTeX, CSL JSON, Unicode/LaTeX normalization, macro, author-date, numeric, localization, cross-chapter, path-boundary, size-limit, entry-limit, diagnostics, clean-wheel, and PDF destination regression coverage.

## 1.16.0 - 2026-07-10

### Added
- Added an opt-in semantic cross-reference engine for labeled figures, tables, display equations, and code listings in both single-file and multi-file Book Mode output.
- Added continuous global numbering and chapter-scoped numbering, localized English/Persian captions and references, stable PDF destinations, and generated lists of figures, tables, equations, and listings.
- Added `--references`, `--numbering-scope`, and paired list-generation CLI overrides plus matching versioned `[references]` project configuration and front-matter fields.

### Changed
- Resolved Book Mode labels only after all chapters are assembled so references can target objects in another listed chapter while retaining deterministic manifest order and chapter namespaces.
- Extended the clean-wheel release gate to build a labeled multi-chapter book and verify all four numbered object kinds and their PDF named destinations.

### Fixed
- Recalculated caption direction/profile classes after semantic label markers are removed, preserving Persian and mixed-script caption typography.
- Kept reference tokens inside code, links, scripts, styles, and literal contexts unchanged and avoided bidi isolation before semantic reference resolution.

### Security
- Kept reference labels document-internal and independent of local-file or URL resolution; labels cannot expand filesystem access, enable scripts, or bypass safe-HTML and asset policies.
- Failed before Chromium on duplicate labels, unresolved references, kind mismatches, malformed labels, and ambiguous markers.

### Tests
- Added single-file and Book Mode regression coverage for all object kinds, localized numbering, punctuation boundaries, cross-chapter resolution, duplicate/unresolved diagnostics, raw HTML handling, generated lists, CLI/config precedence, and clean-wheel PDF destinations.

## 1.15.0 - 2026-07-10

### Added
- Added deterministic multi-file Book Mode driven by the ordered `[book].chapters` manifest in `mardas.toml`, with `init --book`, `validate-book`, `explain-book`, and `build-book` workflows.
- Added one-pass book assembly with project-level cover/output settings, per-chapter Markdown/front matter, global TOC and PDF outline generation, chapter title overrides, optional inter-chapter page breaks, and atomic debug-HTML/PDF output.
- Added safe shared project-root asset resolution and internal links between listed chapters, including optional heading fragments.

### Changed
- Namespaced chapter heading, anchor, and footnote IDs before assembly so repeated titles and local identifiers remain unambiguous across the complete book.
- Extended the clean-wheel release gate to create, validate, explain, and render a starter two-chapter book from the installed console entry point.
- Refactored the PDF pipeline to accept an already parsed `MarkdownRenderResult`, allowing single-file and Book Mode output to share the same cover, Chromium, metadata, outline, page-label, and atomic-write implementation.

### Security
- Restricted chapter sources and shared assets to the project root after symlink resolution, rejected absolute or duplicate chapter paths and source/output collisions, and kept unrelated local filesystem links inert.
- Limited Book Mode manifests to 512 ordered chapters and supported Markdown extensions before rendering begins.

### Tests
- Added Book Mode regression coverage for manifest ordering, chapter containment, duplicate sources, ID namespacing, title overrides, shared assets, cross-chapter links, page breaks, output collisions, JSON diagnostics, starter-project generation, and clean-wheel release execution.

## 1.14.0 - 2026-07-10

### Added
- Added versioned `mardas.toml` project configuration with nearest-ancestor discovery, explicit `--config` selection, `--no-config` opt-out, schema validation, safe relative-path resolution, and deterministic CLI override precedence.
- Added `mrs-md2pdf init`, `validate`, `doctor`, and `explain-config` workflows with stable text/JSON diagnostics for automation and local environment inspection.
- Added diagnostic coverage for malformed TOML/YAML, unknown or invalid configuration values, missing configured assets, blocked local/remote images, heading hierarchy jumps, risky security settings, missing dependencies, Chromium discovery, and packaged MathJax integrity.

### Changed
- Added paired CLI overrides such as `--no-toc`, `--cover`, `--header-footer`, `--mathjax`, `--safe-html`, and `--block-remote-assets` so command-line automation can override either side of a project boolean.
- Extended the clean-wheel release gate to initialize, validate, inspect, and diagnose a real project using only installed console entry points.
- Added the Python 3.10 `tomli` compatibility dependency while using the standard-library `tomllib` on Python 3.11 and newer.

### Fixed
- Resolved appearance consistently as `CLI > mardas.toml > front matter > built-in defaults`, including syntax highlighting, document CSS, footer styling, and Chromium PDF output.
- Corrected clean-wheel release verification to check the stylesheet and branding asset names that are actually shipped in the package.
- Restored front-matter appearance behavior when no CLI or project override is supplied instead of silently forcing CLI parser defaults.

### Security
- Warned explicitly when project configuration enables unsanitized HTML or remote network assets and documented command-line safety overrides.
- Rejected oversized project files, unknown schema sections/keys, unsupported schema versions, invalid values, and invalid configured paths before Chromium starts.

### Tests
- Added project-configuration, precedence, path-resolution, structured-diagnostic, project-command, clean-release, and front-matter appearance regression coverage.

## 1.13.40 - 2026-07-10

### Security
- Restricted Markdown, safe-HTML, and front-matter branding assets to supported regular images inside the document root, including symlink containment, MIME validation, and size limits.
- Made Studio Fast Preview block remote/local image fetches and unsafe or filesystem link schemes while keeping PDF-like Preview as the authoritative renderer-backed path.
- Added bounded YAML depth, node-count, scalar-size, and cycle validation; bounded Studio export concurrency; and isolated stale-preview coordination per browser tab.

### Changed
- Converted A0-A6, B0-B6, Letter, Legal, Tabloid, and Ledger formats to explicit Chromium dimensions and bounded custom page dimensions to 10-5000 mm per side.
- Made Python wheel and source-distribution builds deterministic and connected the tagged-release workflow to the consolidated release gate.
- Added IPv6 loopback Studio support and kept duplicate asset basenames in separate directories without ambiguous root-level fallback aliases.

### Fixed
- Prevented PDF output or debug HTML from overwriting the Markdown source through direct, relative, symlink, hardlink, or case-normalized path aliases.
- Wrote final PDF and debug HTML artifacts atomically so a failed post-processing/write step preserves the previous valid output.
- Rejected malformed or recursive front matter with actionable diagnostics, accepted UTF-8 BOM input, and preserved math/footnote-like text inside indented code and multiline code spans.
- Deduplicated manual and generated heading IDs, blocked machine-local `file:` PDF annotations, and converted common CLI failures to concise messages without default tracebacks.

### Tests
- Added regression coverage for local-file disclosure, output-path aliases, atomic-write failures, Fast Preview URL policy, bounded YAML, Studio concurrency/tab isolation, page dimensions, deterministic distributions, IPv6, BOM input, code-literal preservation, and controlled CLI diagnostics.

## 1.13.39 - 2026-07-10

### Security
- Enforced required, non-negative, bounded `Content-Length` values, rejected unsupported `Transfer-Encoding`, and added deadlines plus exact-length checks for Studio request-body reads.
- Prevented Studio renderer exceptions, temporary paths, and operating-system details from being returned to API clients while retaining full local error logs.

### Fixed
- Rejected normalized, case-insensitive, ancestor/descendant, and basename-fallback collisions between attached Studio assets before writing any temporary files.
- Protected Studio working files such as `document.md` and the requested PDF output path from attached-asset overwrite collisions.

### Tests
- Added HTTP-level regression coverage for negative request lengths, unsupported transfer encodings, controlled renderer failures, conflicting asset paths, reserved paths, and partial-write prevention.

## 1.13.38 - 2026-07-04

### Changed
- Polished Studio UI/UX for final-workflow maturity with clearer Preview status pills, less-clipped header controls, and non-blocking toast feedback for high-signal actions.
- Improved command palette keyboard navigation with active-item tracking, Arrow/Home/End movement, and `aria-selected` state.

### Fixed
- Prevented the Preview status badge from visually clipping short status labels in narrow preview panes.
- Replaced the confusing first-run restore failure message with a neutral local-state reset status.

## 1.13.37 - 2026-07-04

### Changed
- Limited Studio editor-to-preview scroll synchronization to Fast preview only, because PDF-like preview includes renderer-only cover, TOC, and page geometry that cannot stay ratio-synchronized with the Markdown source pane.
- Tuned PDF-like preview scrollbars so dark PDF previews inside the dark Studio interface no longer show a bright native scrollbar.

### Fixed
- Reworked Markdown editor line numbers into explicit virtualized rows with physical-line wrapping disabled, padding-aware scroll calculations, and resize-aware gutter refreshes for long documents.

### Tests
- Added regression coverage for Fast-only scroll synchronization, hardened long-document line-number gutter behavior, PDF-like preview scrollbar styling, and updated Studio browser audit checks.

## 1.13.36 - 2026-07-04

### Changed
- Kept Studio PDF-like preview responsive on very large drafts by pausing automatic renderer-backed refreshes above the large-document threshold and exposing an explicit manual refresh action.
- Made local auto-save messaging more explicit when a draft is too large to persist in browser storage.

### Fixed
- Allowed empty Studio drafts to render as a blank PDF-like preview instead of surfacing a backend error while keeping PDF export validation strict.
- Made Studio static GET routing ignore query strings so cache-busted `/index.html?...` and asset requests resolve correctly.
- Bounded generated Studio filenames and asset path segments with hash suffixes while preserving file extensions.
- Emitted UTF-8-safe `Content-Disposition` filenames for Studio PDF downloads so non-ASCII filenames do not break HTTP headers.
- Added a large debug-HTML export confirmation and retained delayed object-URL cleanup for browser download stability.

### Tests
- Added regression coverage for empty draft previews, query-string GET routing, filename/path length bounds, UTF-8-safe attachment headers, and large-document Studio preview safeguards.

## 1.13.35 - 2026-07-04

### Changed
- Improved developer and release workflow reliability by letting `python -m pytest` find the `src/` package directly from a checkout and by documenting the full-source distribution intent.
- Made the full visual QA matrix more resumable and observable by skipping already completed child chunks, writing active-chunk heartbeat data, and preserving elapsed-time metadata in the matrix summary.
- Clarified Studio Fast preview as an approximate, browser-local editing preview while keeping PDF-like preview as the renderer-backed fidelity path.

### Fixed
- Hardened Studio project-bundle loading so oversized, duplicate, malformed, or unsafe embedded assets are skipped before they enter browser state, with a clear skipped-asset warning.
- Delayed browser object-URL revocation for Studio downloads to avoid download races in stricter browsers.
- Warned when Markdown is too large for local auto-save instead of implying that the full draft was saved locally.

### Tests
- Added regression coverage for checkout-local pytest configuration, source-distribution manifest policy, visual-QA resumability/heartbeat controls, Fast-preview wording, and Studio project-bundle asset validation.

## 1.13.34 - 2026-07-04

### Fixed
- Made the Studio direction toggle update the real document direction option and rerender PDF-like preview, so the visible renderer-backed preview matches the exported RTL/LTR setting instead of only flipping the legacy fast-preview container.
- Rebuilt the Studio “Copy CLI command” workflow around POSIX shell quoting so filenames, metadata, brand labels, watermarks, spaces, quotes, and Persian text produce a safer command line.
- Added latest-only request coordination for renderer-backed Studio previews so stale PDF-like preview requests return `stale_preview` instead of updating the UI after newer edits.

### Documentation
- Clarified Studio Mermaid wording so the fast browser preview is described as an approximate flowchart preview while exported PDFs continue to use the offline Mermaid flowchart renderer subset.

### Tests
- Added regression coverage for Studio direction/export synchronization, CLI command quoting, and latest-only backend preview request handling.

## 1.13.33 - 2026-07-04

### Fixed
- Hardened Studio render endpoints so `/api/render` and `/api/render-html` require same-origin requests, trusted local Host headers, `Content-Type: application/json`, and a per-session Studio API token.
- Added `X-Content-Type-Options: nosniff` to Studio text, JSON, asset, and PDF responses to reduce browser content-type ambiguity.

### Tests
- Added regression coverage for Studio API Host, Origin, Fetch Metadata, media-type, and token rejection paths, including an HTTP-level cross-origin POST check.

## 1.13.32 - 2026-07-04

### Changed
- Removed the experimental automatic page-boundary guides from Studio PDF-like preview because screen-side DOM height simulation could not reliably match Chromium's print/PDF pagination across covers, TOCs, tables, images, code blocks, and font loading.
- Kept the lighter PDF-like preview as a renderer-backed page-sized sheet with margins, auto-fit scaling, and explicit Markdown page-break indicators only.

### Tests
- Updated Studio GUI regression and browser visual-audit checks to verify the PDF-like preview CSS is injected while deprecated page-guide overlays are absent.

## 1.13.31 - 2026-07-04

### Changed
- Reworked Studio PDF-like page indicators from intrusive center-page boundary overlays to non-intrusive page guides that stay in the page margins and no longer cover document content.
- Reduced Studio editing overhead by caching Markdown line counts, virtualizing gutter updates through animation frames, throttling editor-to-preview scroll synchronization, and replacing split-based word/line counting with allocation-light counters.
- Added cancellation and request-key caching for renderer-backed PDF-like preview refreshes so stale preview requests do not update the UI and repeated unchanged renders are skipped.

### Tests
- Updated Studio GUI regression and browser visual-audit checks for the margin-based PDF-like page guides and long-document editor behavior.

## 1.13.30 - 2026-07-03

### Changed
- Removed the Studio Exact PDF preview mode because the renderer-backed PDF-like preview provides the useful workflow with far less latency and fewer browser-viewer failure modes.
- Added visible page-boundary markers to the Studio PDF-like preview so users can see where one simulated PDF page ends and the next page starts while editing.
- Virtualized Markdown editor line numbers so long documents continue numbering correctly beyond several thousand lines without rendering a huge line-number text node.
- Synchronized editor scroll with the renderer-backed preview iframe when PDF-like preview is active.

### Tests
- Expanded Studio visual audit checks to verify PDF-like page markers and long-editor line numbering through a browser session.
- Updated GUI regression tests for the two-mode preview model and the paged PDF-like preview CSS/JavaScript.

## 1.13.29 - 2026-06-29

### Changed
- Made Studio default to a renderer-backed PDF-like preview that injects screen-only page sizing, margins, auto-fit scaling, paper shadow, and visible page-break markers so the preview is closer to exported PDF geometry.
- Added an optional Exact PDF preview mode that renders the current document through the existing PDF endpoint and displays the result in the browser PDF viewer for highest-fidelity manual checks.
- Refreshed Studio preview automatically when export options or attached assets change, instead of waiting for the next Markdown edit.

### Tests
- Added regression coverage for Studio preview page dimensions, injected preview CSS and scaling script, exact-PDF preview wiring, option/asset-triggered preview refreshes, and the live Studio visual-audit preview path.

## 1.13.28 - 2026-06-29

### Fixed
- Prevented multi-digit numbered-code gutters from wrapping one digit per visual row in print/PDF output, especially for `linenostart` values above 9 in dark academic/textbook visual QA cases.

### Tests
- Added regression coverage for numbered-code gutter CSS so print wrapping rules cannot reapply to line-number cells.
- Verified the final visual QA matrix across all 56 style/palette/mode combinations for both appearance and feature-heavy samples, plus the Studio browser screenshot audit.

## 1.13.27 - 2026-06-29

### Fixed
- Blocked remote Markdown images in the direct `render_markdown` API by default, matching the file-based renderer and CLI privacy boundary while still honoring `allow_remote_images=True`.
- Preserved Studio attached asset paths with spaces and Unicode characters so Markdown image references and custom brand logos resolve to the uploaded browser asset names instead of dash-renamed sanitized paths.

### Tests
- Added regression coverage for direct remote-image blocking, direct remote-image opt-in, and Studio attached assets with whitespace/Unicode path segments.

## 1.13.26 - 2026-06-21

### Fixed
- Changed Markdown footnote rendering from a single document-end endnote section to page-local print footnote blocks inserted near the reference, avoiding guide footnote calls that jump to the final page of the PDF.
- Updated the official English and Persian guide footnote samples so the Persian/RTL smoke sample and the dedicated Footnotes section use distinct footnote IDs and demonstrate local footnote placement.

### Tests
- Added regression coverage for page-local footnote sections, repeated-reference local clones, localized Persian footnote markers, and footnote print CSS.

## 1.13.25 - 2026-06-21

### Documentation
- Removed the standalone feature/reference docs for appearance, branding, Markdown fidelity, PDF navigation, PDF typography, Persian/RTL, Studio, and visual QA because their user-facing content now belongs in the English and Persian guides.
- Polished the guide-first documentation wording in the README, docs index, documentation policy, and both guides so the guides are explicitly the complete feature manual and live renderer sample.

### Tests
- Updated documentation integrity tests to reject stale feature-reference links and confirm the guides cover the retired feature areas.

## 1.13.24 - 2026-06-21

### Documentation
- Reorganized the documentation architecture around a guide-first model: the English and Persian guides are now explicitly the canonical user manuals and live renderer samples, while focused docs are maintainer contracts instead of parallel tutorials.
- Rewrote the feature-reference docs for appearance, branding, Markdown fidelity, PDF navigation, PDF typography, Persian/RTL quality, Studio, and Visual QA to reduce guide/reference duplication and clarify ownership.
- Updated the docs index, documentation policy, README documentation map, and guide notes to make the new ownership model visible.

### Tests
- Added documentation-integrity coverage for the guide-first model and the maintainer-contract classification of focused docs.

## 1.13.23 - 2026-06-21

### Documentation
- Corrected the official advanced-code-fence samples so `{2,5-6}` visibly highlights three existing code rows instead of demonstrating an out-of-range range on a four-line snippet.
- Updated the Studio code insertion template and Markdown fidelity guide to use the same six-line sample, making line-highlight ranges easier to verify visually.

### Tests
- Added regression coverage for visible multi-line highlight ranges and for documentation/Studio samples that keep `{2,5-6}` within the actual code block length.

## 1.13.22 - 2026-06-21

### Fixed
- Removed the final highlighted-code indentation drift by eliminating the highlighted-line padding that shifted highlighted content one character to the right of the following indented code rows.
- Normalized highlighted-line CSS to inherit the code row's font size and line height so advanced numbered code blocks use the same vertical rhythm as ordinary code blocks.

### Tests
- Added regression coverage that highlighted numbered code strips preserve leading spaces, do not reintroduce the old padding offset, and keep the line break outside the `.hll` wrapper.

## 1.13.21 - 2026-06-21

### Fixed
- Fixed the remaining advanced highlighted-code indentation defect by normalizing Pygments highlighted-line HTML so the newline is emitted outside the `.hll` wrapper. This keeps full-row highlight strips without letting the highlighted inline box consume the next line's leading spaces.

### Tests
- Added regression coverage that verifies the line after a highlighted numbered-code row keeps its leading indentation in the generated HTML.

## 1.13.20 - 2026-06-21

### Fixed
- Corrected numbered-code gutter alignment for highlighted advanced code blocks by keeping Pygments line-number spans inline. The previous block display override doubled the effective gutter line spacing and made numbers drift away from code rows.
- Changed highlighted code rows from block boxes to full-width inline-block highlights so highlighted lines remain visually continuous without adding extra line breaks inside `<pre>` layout.

### Tests
- Added regression assertions that numbered-code gutter spans stay inline and highlighted rows use full-width inline-block styling.

## 1.13.19 - 2026-06-21

### Fixed
- Aligned advanced numbered-code gutters with the actual code rows by moving numbered-code sizing and padding to shared per-style code metric tokens, then reusing those same metrics for both the code cell and the line-number gutter.
- Removed another source of numbered-code drift: the gutter no longer depends on hardcoded textbook/academic padding overrides inside the renderer, so future style tuning stays synchronized automatically.

### Tests
- Added regression coverage that every bundled style emits the shared code metric tokens and that numbered-code CSS uses those tokens for gutter/code alignment.

## 1.13.18 - 2026-06-21

### Fixed
- Centered Mermaid edge-label text inside its rounded label chips more reliably for Chromium PDF output by switching chip text to an explicit `tspan` vertical offset instead of relying on SVG baseline heuristics alone.
- Removed the stray dark badge backgrounds that Pygments emits around numbered-code gutter spans so advanced code blocks render clean line numbers without per-line boxes.
- Added support for common pipe-labelled dotted Mermaid edges such as `-.->|no| Retry`, so practical guide diagrams keep the expected label and retry node in offline rendering.

### Tests
- Added regression coverage for Mermaid chip text centering, pipe-labelled dotted Mermaid edges, and clean numbered-code gutter CSS overrides.

### Fixed
- Reworked highlighted code-line backgrounds so advanced fenced-code samples with line numbers stay readable on dark code surfaces in light styles and in dark-mode textbook/academic output, instead of resolving to pale callout-style or light-surface fills.
- Made mixed Persian/Latin table cells in Persian documents resolve to an explicit RTL base direction while keeping Latin identifiers isolated, fixing tables whose Persian descriptions were visually laid out as LTR.

### Tests
- Added regression coverage for code highlight contrast CSS and Persian mixed-script table direction voting.

## 1.13.16 - 2026-06-21

### Fixed
- Improved dark-mode palette tokens so low-saturation palettes such as `slate` and `neutral` keep readable TOC links, headings, and accents on dark textbook/academic surfaces.
- Marked code blocks containing Persian/Arabic script with stable CSS hooks and used Persian-capable font fallback inside those blocks so Persian YAML/string samples render joined and readable.
- Hardened `scripts/build_examples.sh` to render guide PDFs through the shared process-tree-safe command runner and force `--progress off` for non-interactive release builds.

### Tests
- Added coverage for dark-mode palette contrast tokens, RTL-script code-block CSS, and process-tree-safe guide example builds.

## 1.13.15 - 2026-06-21

### Fixed
- Made the `MARDAS_RENDER_SMOKE=1` path in `scripts/check.sh` run the guide render through the process-tree-safe Visual QA command helper so CI/release smoke checks do not hang when Chromium descendants inherit captured output handles.
- Added `MARDAS_RENDER_SMOKE_TIMEOUT` for a bounded outer smoke-render timeout independent of the Chromium `MARDAS_TIMEOUT_MS` page timeout.
- Disabled third-party pytest plugin autoload inside `scripts/check.sh` by default, with `MARDAS_ALLOW_PYTEST_PLUGINS=1` as an explicit opt-in, so local release checks stay deterministic after Playwright smoke renders.

### Documentation
- Synced README badge and English/Persian guide metadata to version `1.13.15`.

### Tests
- Added release-script regression coverage for the process-tree-safe render-smoke wrapper.

## 1.13.14 - 2026-06-21

### Fixed
- Replaced the heavyweight guide architecture SVG wrapper with an optimized document-local PNG so guide builds no longer embed a large base64 raster image inside SVG and then inside HTML.
- Updated English/Persian guide image and safe-HTML samples to use `images/architecture.png` while preserving the approved banner artwork.

### Documentation
- Clarified the guide media asset contract in `docs/BRANDING.md` and `docs/PDF-TYPOGRAPHY.md` so sample media stays lightweight and build-friendly.
- Synced README badge and English/Persian guide metadata to version `1.13.14`.

### Tests
- Updated guide media integrity tests to reject the removed nested-base64 `architecture.svg` path and enforce the optimized PNG contract.

## 1.13.13 - 2026-06-21

### Changed
- Switched the Studio topbar brand mark from the raster logo to a dedicated monochrome SVG mask so the GUI uses a true vector logo.
- Made the Studio brand mark inherit the exact same color as the `Mardas MD2PDF Studio` wordmark in both dark and light interface modes.

### Documentation
- Documented the new Studio-specific vector brand-mask asset in `docs/BRANDING.md`.
- Synced README badge and English/Persian guide metadata to version `1.13.13`.

### Tests
- Extended GUI, packaged-asset, and documentation-integrity tests to enforce the vector-branding contract for Studio.

## 1.13.12 - 2026-06-21

### Changed
- Replaced the guide-local architecture banner artwork with the supplied structured print pipeline illustration so the English and Persian manuals use the cleaner approved visual.
- Replaced the repository `README.png` hero artwork with the supplied dark banner so the public landing image matches the intended product presentation.
- Removed the obsolete `docs/guides/images/logo.svg` file from the guide media contract; the guide directory now keeps only the local `architecture.svg` sample and the approved `logo.png` copy.

### Documentation
- Documented the asset-layout policy for runtime packaged assets, guide-local documentation media, and the repository-level README artwork in `docs/BRANDING.md`.
- Synced README badge and English/Persian guide metadata to version `1.13.12`.

### Tests
- Updated documentation/media integrity tests so malformed guide-local `logo.svg` artwork cannot silently return and the replacement architecture banner contract stays explicit.

## 1.13.11 - 2026-06-21

### Changed
- Adopted the supplied Mardas MD2PDF application logo as canonical packaged full-color and white transparent PNG assets for Studio, cover branding, README artwork, and guide-local documentation assets.
- Centralized built-in product logo resolution and Studio brand-asset routing in `brand_assets.py` so renderer and GUI paths use the same asset contract.
- Refreshed the README hero image to use the dedicated application logo instead of the older generic mark artwork.

### Fixed
- Removed the legacy raster logo fallback from runtime branding and Studio asset routes so built-in branding no longer depends on the old Mardas logo file.

### Tests
- Added regression coverage for canonical app-logo packaging, transparent PNG dimensions, Studio routing, renderer fallback order, and documentation references.

## 1.13.10 - 2026-06-21

### Fixed
- Replaced the chunked Visual QA runner's pipe-captured subprocess execution with the shared process-tree-safe command helper so batch audits report failed child chunks instead of hanging when Chromium or Poppler descendants inherit output handles.
- Aligned the guide media regression contract with the current architecture-banner samples: guide Markdown must use the document-local `images/architecture.svg` sample, keep the packaged `images/logo.svg` asset available, and avoid reintroducing direct logo embeds in the manuals.

### Tests
- Added regression coverage for chunked Visual QA command capture and child-failure reporting.
- Updated guide media integrity coverage so contradictory `images/logo.svg` expectations cannot make the baseline test suite fail.

## 1.13.9 - 2026-06-20

- Added a dedicated white vector cover-label mark for built-in Mardas MD2PDF branding while keeping the full-color mark for Studio and document-local examples.
- Refined guide cover-brand mark sizing across packaged print styles so the logo remains centered in the compact label chip.
- Reworked the official guide architecture/banner SVG for cleaner spacing, alignment, and emerald visual consistency.
- Updated the English and Persian guide safe-HTML image sizing samples to reuse the architecture/banner asset instead of switching to the raw logo.
- Strengthened documentation integrity tests for the white cover-mark asset and the guide image-sample contract.

## 1.13.8 - 2026-06-20

### Fixed
- Fixed Persian checked task-list items so `[x]` markers still become disabled PDF checkboxes after mixed-script isolation wraps the Latin `x`.
- Rebalanced the official guide image samples so the standalone project mark remains compact and no longer forces a nearly blank Persian guide page.
- Updated the guide architecture diagram to use the official Mardas MD2PDF mark instead of the temporary literal `M` placeholder.

### Documentation
- Synced README badge and English/Persian guide metadata to version `1.13.8`.

### Tests
- Added regression coverage for Persian checked task lists and the official guide logo sample sizing.

## 1.13.7 - 2026-06-20

### Changed
- Adopted the dedicated Mardas MD2PDF project logo as packaged SVG assets for the built-in cover brand label and Studio UI.
- Kept the legacy raster compatibility fallback while preferring `mardas-md2pdf-mark.svg` for new built-in product branding.

### Documentation
- Documented the official mark, app icon, guide-local logo copy, and custom-brand usage boundaries in the branding reference.
- Synced README badge and English/Persian guide metadata to version `1.13.7`.

### Tests
- Added regression coverage for the packaged SVG logo asset contract and updated Studio logo checks for the new colored project mark.

## 1.13.6 - 2026-06-20

### Fixed
- Restored the product cover brand label to use the active appearance palette instead of a hard-coded blue product mark, so the official emerald guides keep the old compact label geometry while matching the current cover theme.
- Kept the guide cover brand label shadowless and compact, with the built-in Mardas product logo tinted through the surrounding palette-aware mark frame.

### Documentation
- Synced guide metadata, README badge, and changelog to version `1.13.6`.

### Tests
- Added regression coverage that rejects hard-coded blue product-brand styling and requires the modern emerald guide label to stay palette-aware and shadowless.

## 1.13.5 - 2026-06-20

### Fixed
- Restored the official guide cover label to the exact built-in product-branding path used by the earlier good guide examples: packaged Mardas logo, compact rounded pill, established two-line typography, and no drop shadow.
- Removed the temporary guide-local `images/brand-mark.svg` artwork from the official guides so the cover label no longer renders as a separate custom brand asset.
- Reintroduced product/custom brand classes only as stable render hooks so product labels can keep the classic Mardas styling while custom organization brands remain neutral.

### Documentation
- Clarified that official guides use `branding.mode: full` without custom `brand` metadata to preserve the built-in Mardas product label.

### Tests
- Updated regression coverage to require the official guides to avoid custom brand metadata and to keep the modern emerald cover label shadowless.

## 1.13.4 - 2026-06-20

### Fixed
- Restored the classic guide cover branding label: a compact rounded pill, circular optical logo frame, and the guide-local `images/brand-mark.svg` artwork used by the earlier official examples.
- Removed the product/custom cover-brand class split introduced in the previous branding polish so guide covers do not regress to a squared or overbuilt badge.

### Documentation
- Clarified that official guides intentionally pin the local brand mark to preserve the established guide cover identity.

### Tests
- Restored regression coverage that requires the official guide front matter to keep `brand.logo: images/brand-mark.svg`.

## 1.13.3 - 2026-06-20

### Changed
- Restored the official guide cover branding to use the packaged Mardas product logo instead of the temporary guide-local M-style placeholder mark.
- Refined the cover branding badge frame so product branding keeps the compact professional label while custom organization brands remain neutral and user-owned.
- Reworked the guide SVG brand samples and architecture diagram so they use a Mardas-like organic product mark rather than a literal `M` icon.

### Fixed
- Fixed the Persian guide pipeline code sample so the mixed RTL/LTR text no longer reorders visually inside the code block.

### Tests
- Updated regression coverage for guide branding metadata, packaged product logo usage, and the product/custom cover badge class contract.

## 1.13.2 - 2026-06-20

### Changed
- Strengthened the official guide visual identity so the English and Persian examples use a visibly emerald Mardas cover, callout, table, heading, and footer accent contract instead of only storing `palette: emerald` in front matter.
- Added a compact emerald guide brand mark and wired the official guides to use it for cover branding.
- Updated guide quickstart and automation examples to prefer the same `modern + emerald + light` appearance used by the official examples.

### Fixed
- Fixed remaining guide drift where the cover and semantic callouts still looked blue/violet/yellow despite the guide metadata declaring the emerald palette.

### Tests
- Added regression coverage for the official guide brand mark, guide metadata, and modern-emerald callout/cover CSS contract.

## 1.13.1 - 2026-06-20

### Changed
- Reworked printed footer layout so the running metadata line stays truly centered while titles and page numbers align cleanly on the outer edges in both LTR and RTL guides.
- Standardized both official guides on the `modern + emerald + light` appearance so the documentation, Studio palette, and embedded brand artwork follow one consistent Mardas visual language.
- Refreshed the official guide SVG brand samples with a cleaner Mardas-style logo plate and a matching emerald architecture diagram.

### Fixed
- Fixed asymmetric Persian footer placement where page numbers and document titles no longer sat flush on the expected outer edges.
- Fixed English/Persian guide sample drift caused by using different styles and palettes across the official example PDFs.

### Documentation
- Synced guide metadata, release references, and appearance contracts to version `1.13.1`.

### Tests
- Added regression coverage for footer slot alignment and the shared guide appearance contract.

## 1.13.0 - 2026-06-20

### Fixed

- Reduced PDF preflight font warnings in modern/GitHub output by avoiding environment-specific Inter font embedding in print styles and guide SVG samples.
- Improved footer contrast in dark-mode PDF output so page labels and running metadata stay readable across styles.

### Added

- Added `scripts/check_pdf_preflight.py` for repeatable PDF font, rasterization, and parser-warning checks.
- Added `scripts/run_visual_qa_matrix.py` as a chunked full-matrix Visual QA runner for appearance and feature-heavy PDF audits.
- Added `scripts/release_gate.sh` to consolidate pytest, smoke rendering, guide rebuilds, PDF preflight, bounded Visual QA, and distribution builds into one release command.

### Documentation

- Documented guide-level PDF preflight checks, chunked Visual QA runs, and the consolidated release gate.

### Tests

- Added regression coverage for PDF preflight parsing, explicit appearance triples, chunking contracts, dark footer contrast, guide preflight documentation, and release-gate script wiring.

## 1.12.2 - 2026-06-20

### Fixed

- Stabilized Visual QA subprocess handling so batch renders terminate full process groups on timeout instead of allowing orphaned Chromium or Poppler helpers to hang the matrix.
- Added explicit pdftoppm raster timeouts and clearer failure messages for PDF cases that create a file but do not exit cleanly.
- Polished Studio first-run state messaging so a missing local draft is treated as a clean ready state instead of an error.

### Added

- Added resumable and bounded Visual QA options: `--resume`, `--fail-fast`, `--max-cases`, and `--raster-timeout`.
- Added `--all-appearances` for feature-heavy PDF smoke audits so table, code, Mermaid, MathJax, callout, footnote, caption, and mixed-script coverage can be rendered across the full appearance matrix.
- Added `MARDAS_BUILD_NO_ISOLATION=1` support to `scripts/build_dist.sh` for offline or already-prepared release environments.

### Tests

- Added regression coverage for process-tree timeout handling, bounded all-appearance feature audits, reliable Visual QA CLI controls, Studio first-run status messaging, and the no-isolation build mode.
- Kept release metadata checks compatible with the supported Python 3.10 CI target by avoiding Python 3.11-only `tomllib` in the test suite.

## 1.12.1 - 2026-06-20

### Fixed

- Normalized GitHub/Obsidian callout markers before Persian mixed-script isolation so raw markers such as `[!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, and `[!WARNING]` never leak into rendered Persian PDFs.
- Preserved Persian-localized callout titles while still isolating Latin technical runs in the callout body.

### Tests

- Added regression coverage for Persian callouts in guides and mixed-script prose so future visual audits fail before raw callout markers reach generated PDFs.

## 1.12.0 - 2026-06-20

### Added

- Added Studio project files (`.mardas.json`) that preserve Markdown, export options, and attached asset data for repeatable local workspaces.
- Added a browser-side asset manager with append-only attachment handling, duplicate/limit checks, drag-and-drop support, per-asset removal, and one-click brand-logo assignment.
- Added accurate Studio preview mode and debug HTML export using the Python renderer HTML endpoint without starting Chromium.
- Added a command palette with professional workflow shortcuts for export, debug HTML, project save/open, asset actions, preview mode switching, and sidebar control.

### Documentation

- Expanded Studio workflow documentation and refreshed public version metadata for version 1.12.0.

### Tests

- Added regression coverage for Studio project bundles, asset manager actions, accurate preview/debug HTML hooks, command palette wiring, and keyboard shortcuts.

## 1.11.0 - 2026-06-19

### Added

- Added a Visual QA system for appearance matrix artifacts, feature-heavy PDF smoke artifacts, dependency-free PNG snapshot comparison, and Studio screenshots.
- Added CI artifact publishing for reduced visual QA outputs under `build/visual-qa/` so reviewers can inspect PDFs, PNG renders, manifests, galleries, and Studio screenshots without committing generated artifacts.

### Documentation

- Added `docs/VISUAL-QA.md` and linked it from the README and documentation index.
- Refreshed guide metadata and public version badges for version 1.11.0.

### Tests

- Added regression coverage for visual QA helper scripts, PNG statistics/diff behavior, filtered appearance audits, snapshot comparison summaries, Visual QA documentation links, and CI artifact wiring.

## 1.10.0 - 2026-06-19

### Fixed

- Improved print-flow density for medium and long technical blocks so moderately large tables, code listings, and Mermaid diagrams consume less vertical space without clipping content.
- Added medium-size print-flow classes for code blocks and tables, allowing semi-large tables to split at row boundaries instead of moving as one sparse page block.

### Documentation

- Updated the PDF typography guide, public README badge, and guide metadata for version 1.10.0.
- Closed the Persian/RTL quality reference with a release-facing contract for mixed-script prose, generated labels, TOC layout, footnotes, captions, table audit hooks, and guide sample policy.
- Linked the Persian/RTL reference from the long-form documentation index.

### Tests

- Added regression coverage for medium code/table flow hints and the corresponding print-density CSS contracts.

## 1.9.9 - 2026-06-19

### Fixed

- Tuned Mermaid diagram contrast in dark mode so diagram panels, SVG backgrounds, node fills, labels, borders, and caption accents use a complete dark-surface variable contract instead of inheriting only generic panel colors.
- Brightened Mermaid strokes and label chips in dark appearance combinations, including low-accent palettes such as neutral and slate, without changing Mermaid parsing or supported syntax.

### Documentation

- Updated the Markdown fidelity reference and guide metadata for version 1.9.9.

### Tests

- Added regression coverage to ensure every dark style/palette combination emits the full Mermaid contrast variable set and that renderer CSS consumes those variables.

## 1.9.8 - 2026-06-19

### Fixed

- Isolated Latin technical runs inside Persian mixed-script prose so trailing ASCII punctuation such as `renderer.`, `GitHub Actions.`, and `PDF navigation?` stays attached to the Latin token during PDF rendering.
- Added print CSS for inline LTR isolation spans and external links inside RTL article content without rewriting author text or inline code.

### Documentation

- Updated the Persian/RTL quality reference and guide smoke metadata for version 1.9.8.

### Tests

- Added regression coverage for Persian mixed-script punctuation isolation and verified that inline code remains semantically unchanged.

## 1.9.7 - 2026-06-15

### Fixed

- Restored the Persian printed table of contents to the compact English-like tree layout, keeping section numbers adjacent to titles instead of spreading them across the page.
- Mirrored nested TOC indentation inward from the RTL edge with start-side tree rules, while preserving heading IDs, visible TOC links, and PDF outline destinations.

### Documentation

- Updated the Persian/RTL documentation to describe compact RTL TOC tree behavior and guide smoke references for version 1.9.7.

### Notes

- Synced packaged release metadata and regression contracts with the documented 1.9.7 baseline after archive drift.

### Tests

- Updated regression coverage so Persian TOC CSS must use compact inline rows and must not reintroduce the wide number/title grid split.

## 1.9.6 - 2026-06-15

### Fixed

- Added first-pass nested-list depth metadata and classes for Persian/RTL printed tables of contents so the hierarchy could be regression-tested without changing heading IDs, link targets, or PDF destinations.
- Introduced bidirectional TOC tree CSS hooks; the compact visual layout was refined in 1.9.7 after PDF review.

### Documentation

- Refreshed guide metadata and Persian/RTL smoke references for the 1.9.6 TOC tree hook pass.
- Expanded `docs/PERSIAN-RTL.md` with RTL TOC tree indentation concepts.

### Tests

- Added regression coverage for nested Persian TOC lists, localized nested section numbers, TOC depth metadata, and bidirectional TOC indentation CSS.

## 1.9.5 - 2026-06-15

### Documentation

- Expanded the official English and Persian guides with compact Persian/RTL live smoke samples covering mixed-script prose, Persian and Latin numerals, semantic table captions, and reused footnote references.
- Clarified the documentation policy that guide files must stay readable user manuals while also serving as representative renderer test cases.
- Extended `docs/PERSIAN-RTL.md` with guide live-sample coverage rules for future Persian/RTL renderer changes.

### Tests

- Added documentation integrity checks that ensure the guides continue to exercise Persian/RTL tables, mixed numerals, captions, and repeated footnote references.

## 1.9.4 - 2026-06-15

### Fixed

- Added table-level visual-audit metadata for Persian/RTL tables, including direction profile, number profile, cell direction counts, and numeric-cell counts.
- Added stable TOC item profile hooks so Persian, Latin, mixed-script, and numbered heading titles can be checked in generated HTML/PDF without changing heading anchors.
- Strengthened captioned table handling for Persian captions so RTL table captions, mixed numerals, and table wrappers expose deterministic audit classes.

### Documentation

- Expanded `docs/PERSIAN-RTL.md` with Persian table and TOC visual-audit guidance.

### Tests

- Added regression coverage for profiled Persian TOC items, table-level audit metadata, captioned Persian tables, and the related print CSS selectors.

## 1.9.3 - 2026-06-15

### Fixed

- Polished Persian footnote body profiling so RTL, LTR, mixed-script, and mixed-number footnote content receive stable visual-audit hooks.
- Added explicit caption direction and number-profile metadata for Persian, Latin, and mixed captions without rewriting author text.
- Improved Persian printed footer wording from slash-separated page totals to a more readable localized `صفحه N از M` phrase.

### Documentation

- Expanded `docs/PERSIAN-RTL.md` with Persian footnote, caption, and footer visual-audit guidance.

### Tests

- Added regression coverage for Persian footnote body profiles, caption audit metadata, and localized footer templates.

## 1.9.2 - 2026-06-15

### Fixed

- Polished Persian generated navigation labels by localizing visible TOC section numbers while preserving stable heading IDs and link targets.
- Localized Persian footnote reference markers and footnote list markers without changing deterministic footnote anchors or backlink IDs.
- Added localized PDF page-label cover prefixes for Persian cover/content PDFs and strengthened caption number classes for Persian, Latin, and mixed-number captions.

### Documentation

- Expanded `docs/PERSIAN-RTL.md` with Persian navigation, footnote, and generated-label rules.

### Tests

- Added regression coverage for Persian TOC numbering, footnote markers, PDF page-label prefixes, and caption number profile classes.

## 1.9.1 - 2026-06-15

### Fixed

- Polished Persian numeral and punctuation profiling by distinguishing Persian-only digits, Latin-only digits, mixed numerals, Persian punctuation, and ASCII punctuation inside RTL-dominant text.
- Added caption-specific RTL hooks for Persian, numbered, and mixed Persian/English captions so figure, table, code, and Mermaid captions remain reviewable in generated HTML/PDF.
- Removed generated Python bytecode from the Phase 12 patch history and documented ignore rules in the apply helper.

### Documentation

- Expanded `docs/PERSIAN-RTL.md` with punctuation review rules, numeral classes, and caption-specific RTL hooks.

### Tests

- Added regression coverage for Persian/Latin numeral classification, RTL punctuation markers, Persian caption hooks, and table-cell punctuation/numeral profiling.

## 1.9.0 - 2026-06-15

### Added

- Started Phase 12 RTL/Persian deep quality work with deterministic direction classes for Persian, English, and mixed-script blocks.
- Added table-level RTL/LTR profiling so Persian-heavy tables, English-heavy cells, mixed-direction cells, and mixed Persian/Latin numerals get explicit print CSS hooks.
- Added `docs/PERSIAN-RTL.md` as the focused reference for Persian/RTL authoring, mixed identifiers, numbers, tables, captions, and verification.

### Fixed

- Improved bidi isolation for mixed Persian/English prose, captions, and tables so generated PDFs keep technical identifiers and numbers readable in RTL documents.

### Tests

- Added regression coverage for Persian RTL block classification, mixed numeral detection, RTL table profiling, and the injected CSS rules.

## 1.8.9 - 2026-06-15

### Fixed

- Restored the official English and Persian guide front matter so cover pages again use the intended project title, subtitle, authors, branding, metadata, and full guide-cover layout.
- Removed stray TOC-navigation prose from the YAML front matter of both guides and collapsed duplicated TOC navigation paragraphs in the body.
- Reorganized the changelog into a strictly descending, version-by-version history with complete Phase 11 entries.

### Documentation

- Added `docs/DOCUMENTATION.md` to define the documentation map, guide-as-sample policy, changelog rules, and release documentation workflow.

### Tests

- Added documentation integrity checks for guide front matter, duplicate TOC notes, and changelog ordering.

## 1.8.8 - 2026-06-15

### Fixed

- Completed the Phase 11 visual audit pass for Mermaid label extraction, guide media consistency, and RTL/LTR code isolation.
- Replaced stroked Mermaid edge-label halos with background label chips so PDF text extraction no longer duplicates edge-label glyphs.
- Ensured the public guide Markdown points to document-local SVG assets instead of blocked `README.png` placeholders.

## 1.8.7 - 2026-06-14

### Fixed

- Polished the official guide PDF media audit by synchronizing the documented image snippets with the SVG assets rendered in the live samples.
- Fixed the architecture SVG heading so its leading text is not clipped in generated guide PDFs.
- Collapsed duplicated visible-TOC navigation notes in the English and Persian guides.

## 1.8.6 - 2026-06-14

### Fixed

- Replaced blocked guide image placeholders with document-local SVG assets so the official English and Persian PDF examples demonstrate the successful local-image path.
- Cleaned guide media examples so semantic figure captions and safe HTML images are visible in generated guide PDFs without relying on parent-directory or root-level assets.

## 1.8.5 - 2026-06-14

### Fixed

- Polished PDF footnote references so repeated references use stable numeric markers and unresolved references remain visible instead of becoming broken links.
- Improved printed footnote layout with explicit markers, body content, back-reference links, and page-flow rules that reduce awkward footnote splitting.

### Tests

- Added regression coverage for repeated footnote references, unresolved footnote references, and footnote print CSS.

## 1.8.4 - 2026-06-14

### Fixed

- Polished Chromium PDF running footers with bidi-safe document titles, compact running metadata, localized page labels, and style-aware footer rules.
- Added PDF page labels so viewer page numbering restarts cleanly after a cover page while preserving cover pages as separate front matter.

## 1.8.3 - 2026-06-14

### Fixed

- Promoted common image and table caption patterns into semantic print blocks so captions stay attached to their figure or table in generated PDFs.
- Added consistent caption classes for figures, tables, code listings, and Mermaid diagrams, with print CSS that prevents captions from orphaning away from their associated content.

### Documentation

- Expanded `docs/PDF-TYPOGRAPHY.md` with caption and semantic print-block guidance for English and Persian documents.

### Tests

- Added regression coverage for image captions, table captions, code listing captions, Mermaid diagram captions, and caption-specific print CSS.

## 1.8.2 - 2026-06-14

### Fixed

- Improved PDF print-flow rules so headings stay with following content, paragraphs use orphan/widow protection, and figures, callouts, math displays, Mermaid diagrams, and image placeholders avoid awkward page splits.
- Marked long code blocks and long/wide tables with print-flow hints so compact blocks stay together while large technical blocks can split cleanly instead of leaving large blank pages.

### Documentation

- Added `docs/PDF-TYPOGRAPHY.md` to document print-flow rules, long-code behavior, long-table behavior, and the visual audit checklist for generated PDFs.

### Tests

- Added regression coverage for long code/table print-flow classes and the injected print typography CSS.

## 1.8.1 - 2026-06-14

### Fixed

- Rewrote visible PDF table-of-contents link annotations to explicit heading destinations so printed TOC entries keep working after pypdf metadata writes and cover/content merges.
- Kept PDF viewer outline/bookmarks and visible TOC links bound to the same real heading coordinates instead of relying on viewer-specific named-destination resolution.

### Tests

- Added regression coverage that verifies copied visible TOC link annotations are converted from named destinations to explicit PDF destination arrays.

## 1.8.0 - 2026-06-14

### Fixed

- Preserved Chromium named destinations when pypdf writes metadata or merges cover/content PDFs, restoring clickable table-of-contents links in final PDFs.
- Rebuilt PDF viewer outlines from the same heading IDs used by visible TOC links, so bookmarks jump to real content headings instead of matching TOC rows.
- Added regression coverage for duplicate headings, Persian heading anchors, named destinations, and generated PDF outlines.

### Documentation

- Added `docs/PDF-NAVIGATION.md` and refreshed guide metadata for the PDF navigation fix.

## 1.7.0 - 2026-06-13

### Added

- Improved Markdown feature fidelity for advanced fenced-code metadata, including titles, line numbers, line highlights, aliases, and custom starting line numbers.
- Expanded GitHub/Obsidian-style callout support with additional aliases such as `INFO`, `SUCCESS`, `QUESTION`, `DANGER`, `BUG`, `EXAMPLE`, `QUOTE`, and `ABSTRACT`.
- Added `docs/MARKDOWN-FIDELITY.md` as the dedicated feature reference for supported Markdown syntax and renderer expectations.

### Changed

- Updated the public documentation and guide metadata for the 1.7.0 renderer-fidelity release.

## 1.6.4 - 2026-06-12

### Changed

- Redesigned the Studio sidebar into clear Document, Appearance, Branding, Layout, and Advanced sections.
- Replaced raw style, palette, mode, and branding dropdowns with visual choice cards while keeping the same backend render options.
- Improved Studio CLI-copy output so branding options are included when selected.
- Polished the Studio toolbar, settings sidebar, editor, preview status, and status bar for a clearer daily writing workflow.
- Replaced static Studio view-mode buttons with draggable/resizable panes and an auto-collapsing settings sidebar.
- Retuned the Studio interface to pure light/dark surfaces with thin custom scrollbars and higher-contrast export-button interaction states.
- Replaced emoji-based Studio controls with inline SVG icons, restored the project logo in the header, and refined micro-interactions for cards, accordions, toolbar buttons, and status counters.
- Tightened Studio sidebar scrolling, compacted palette selection into color swatches, improved logo fitting, and raised dark-mode helper-text contrast.

### Added

- Added `docs/STUDIO.md` to document the refined visual workflow and local-export behavior.
- Added a compact Markdown formatting toolbar, editor line numbers, preview render status, and proportional editor-to-preview scroll sync.

## 1.6.3 - 2026-06-10

### Changed

- Made cover branding explicit with `branding.mode: off`, `subtle`, or `full`.
- Changed the default cover behavior to unbranded output, so ordinary user PDFs no longer show a large Mardas MD2PDF brand block.
- Added custom organization branding through `brand.name`, `brand.logo`, `brand.footer`, and matching CLI/Studio options.

### Documentation

- Added `docs/BRANDING.md` and refreshed the English/Persian guides for the new cover branding workflow.

## 1.6.2 - 2026-06-10

### Fixed

- Removed badge-like cover label backgrounds so `cover_label` text no longer looks like an accidental highlight in Persian or English covers.
- Kept academic appearance accents palette-driven instead of forcing the older warm brown/orange palette across all palette choices.
- Aligned numbered code line gutters with code rows and switched highlighted code rows to the active palette accent surface.

### Added

- Added regression checks for palette-pure academic output, non-badge cover labels, and numbered code alignment CSS.

## 1.6.1 - 2026-06-10

### Fixed

- Tuned dark appearance surfaces per style so `modern`, `github`, `textbook`, and `academic` keep distinct dark backgrounds instead of sharing one generic navy surface.
- Aligned dark cover pages with their content surfaces, including the nearly black `textbook` dark output.
- Tinted light cover decorations with the selected palette so palette changes are visible on the cover as well as content pages.

### Added

- Added an appearance matrix audit helper for rendering every `style × palette × mode` combination after visual-system changes.

## 1.6.0 - 2026-06-10

### Changed

- Replaced the older visual controls with one appearance model built from `--style`, `--palette`, and `--mode`.
- Removed the parallel `--theme` and `--profile` CLI options so the public interface stays small and predictable.
- Updated Studio to expose style, palette, and mode controls directly and to copy the new CLI syntax.

### Added

- Added an appearance registry with built-in styles, palettes, mode validation, and list commands.
- Added `docs/APPEARANCE.md` to document the new visual model and front-matter format.

### Documentation

- Refreshed README, English guide, Persian guide, helper scripts, CI smoke commands, and generated guide PDFs for the new appearance workflow.

## 1.5.7 - 2026-06-10

### Fixed

- Validated CLI and Studio page-size values so typos fail early instead of silently falling back to A4.
- Added structured Studio validation for TOC depth, watermark opacity, direction, and boolean render options.
- Blocked remote `http(s)` image assets by default, with an explicit `--allow-remote-assets` opt-in for trusted documents.
- Replaced blocked or missing images with visible placeholders in the generated PDF.
- Added print-fit handling for wide tables and improved theme-aware watermark layering.
- Honored `SOURCE_DATE_EPOCH` for deterministic PDF metadata and example guide builds.

### Documentation

- Documented the post-audit hardening fixes, remote asset boundary, deterministic guide builds, and Studio validation errors.

## 1.5.6 - 2026-06-10

### Fixed

- Improved Studio render error responses with stable JSON error codes and clearer client-side messages.
- Added a warning when the Studio server binds to a non-local host.
- Persisted Studio workspace settings and local drafts in browser local storage, with a reset control and keyboard shortcuts for common actions.

### Documentation

- Documented the polished Studio workflow in the README and user guides.

## 1.5.5 - 2026-06-10

### Added

- Added PDF viewer outline bookmarks generated from Markdown headings.
- Added an optional Chromium PDF smoke test that verifies rendered PDF metadata and outline entries.

### Documentation

- Documented PDF outline navigation in the README and user guides.

## 1.5.4 - 2026-06-10

### Added

- Added reusable maintenance scripts for local checks, guide PDF generation, and Python distribution builds.
- Added a release artifact workflow for tagged builds that uploads Python distributions and regenerated guide PDFs.
- Added release metadata tests to keep version strings, guide metadata, changelog entries, and maintenance scripts in sync.

### Documentation

- Documented the maintenance workflow and updated the release checklist to use the shared scripts.

## 1.5.3 - 2026-06-10

### Fixed

- Blocked unresolved local image sources with a transparent placeholder so Chromium cannot read parent-directory, absolute, missing, or oversized image paths through the document base URL.
- Restricted safe raw-HTML `data:` image URLs to common raster formats and rejected obfuscated URL control characters.
- Made Chromium sandbox mode configurable with `--chromium-sandbox auto|on|off`, keeping sandboxing on for normal users while preserving root/container compatibility.

### Documentation

- Added `SECURITY.md` and documented trusted input boundaries in the README and guides.

## 1.5.2 - 2026-06-10

### Fixed

- Hardened local Markdown image embedding so document-local images still work, while absolute paths, `file:` URLs, parent-directory escapes, and current-working-directory fallbacks are no longer embedded silently.
- Limited Mardas MD2PDF Studio render payloads, Markdown size, asset count, per-asset size, and total attached asset size.

### Added

- Added GitHub Actions CI for linting, pytest, and a Chromium render smoke test.
- Added a release checklist for consistent version bumps, generated examples, tags, and release notes.

### Documentation

- Documented the local-image trust boundary and GUI asset limits.
- Documented the CI and release workflow used to keep patch sets and releases consistent.

## 1.5.1 - 2026-05-26

### Changed

- Bumped the project to version 1.5.1 after progress feedback and Mermaid print-safety work.
- Refreshed the generated guide PDF examples.

## 1.5.0 - 2026-05-26

### Added

- Established the stable public baseline for the Markdown-to-PDF pipeline: Markdown parsing, structured HTML assembly, print CSS, Playwright/Chromium PDF export, and local CLI usage.
- Shipped the baseline English and Persian guide PDFs as real generated examples rather than static screenshots or hand-authored PDFs.
- Consolidated the first complete user-facing workflow around CLI rendering, front matter, cover pages, table of contents, code blocks, math, Mermaid diagrams, images, footnotes, and local Studio export.

### Changed

- Iteratively refined print layout, code block rendering, table behavior, cover metadata, Mermaid sizing, and guide documentation before the structured changelog began.

### Notes

- This is the first structured baseline. The older entries below are reconstructed from the pre-structured project history, baseline documentation, and the capabilities that existed before the 1.5.x hardening and release-process work.

## 1.4.0 - 2026-05-26

### Added

- Added the first local Studio GUI for browser-based Markdown editing, approximate preview, option selection, asset attachment, and PDF export.
- Added GUI routes and assets for a local single-user publishing workflow while keeping the CLI as the automation-friendly interface.
- Added browser-side controls for core document options such as title, author, TOC, cover, page size, direction, and output filename.

### Changed

- Brought the documentation guides closer to live samples by covering the GUI workflow as well as the command-line workflow.

## 1.3.0 - 2026-05-26

### Added

- Added advanced Markdown features needed for technical publishing: GitHub-style task lists and alerts, footnotes, raw HTML sanitization, heading anchors, local image embedding, and manual page breaks.
- Added MathJax support for inline and display equations, with a bundled/offline MathJax asset for reproducible local rendering.
- Added the offline Mermaid flowchart renderer for practical project-documentation diagrams without relying on a CDN or external Mermaid service.

### Changed

- Improved the Markdown-to-HTML normalization layer so code, math, Mermaid, footnotes, and safe HTML could coexist in the same document without corrupting each other.

## 1.2.0 - 2026-05-26

### Added

- Added Persian, English, and mixed RTL/LTR document support with direction-aware body flow, cover labels, table cells, code blocks, metadata labels, and UI strings.
- Added Persian-friendly typography assumptions and font fallback behavior so generated PDFs remained readable when documents mixed Persian prose with English identifiers.
- Added professional cover-page metadata fields such as title, subtitle, authors, date, institution, course, status, version, and keywords.

### Changed

- Refined page flow, cover structure, and content direction handling for reports, guides, and university-style documents.

## 1.1.0 - 2026-05-26

### Added

- Added the first complete CLI rendering surface with input/output paths, metadata overrides, TOC controls, cover toggles, page size/margin options, progress output, and debug HTML export.
- Added table-of-contents generation from Markdown headings and baseline page-number/footer rendering for printable PDFs.
- Added local-image handling for document assets referenced from Markdown.

### Changed

- Moved the renderer toward a browser-first model where Chromium performs the final print layout from structured HTML and CSS.

## 1.0.0 - 2026-05-26

### Added

- Introduced the core `Markdown -> Structured HTML -> Chromium PDF` architecture.
- Added the initial Python package, renderer entry point, Markdown parsing layer, bundled CSS assets, and Playwright/Chromium PDF export path.
- Added the first documentation skeleton and generated examples that established the project as a local Markdown publishing tool rather than a one-off converter script.

## 0.x - 2026-05-26

### Notes

- Prototype phase for validating the feasibility of using Markdown, HTML/CSS print rules, and Chromium to generate Persian/English technical PDFs.
- Experiments from this period were folded into the `1.0.0` baseline once the converter became a usable project.
