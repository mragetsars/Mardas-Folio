# Security Policy

Mardas MD2PDF is a local publishing tool. It is safe by default for normal
Markdown authoring, but it is not a sandbox for hostile documents. Treat
Markdown, front matter, raw HTML, attached Studio assets, logos, watermarks, and
local image references as author-controlled input.

## Supported versions

Security fixes are made on the current `master` branch and the latest tagged
release. When reporting an issue, include the Mardas MD2PDF version, Python
version, operating system, and the command or Studio settings used to render the
PDF.

## Threat model

The project protects against accidental local-file disclosure, unexpected network
fetches, active HTML content, and unsafe Chromium defaults during ordinary local
PDF generation. It does not claim to safely execute arbitrary hostile Markdown on
a shared public service. For untrusted documents, run the converter in a
container, VM, disposable user account, or CI job with a restricted filesystem and
network policy.

## Input boundaries

### Local files and images

- Markdown images, safe-HTML images, and front-matter branding logos are
  resolved relative to the Markdown document.
- Branding assets must be regular supported image files inside the document root;
  absolute paths, parent-directory escapes, and symlink escapes are rejected.
- Safe local images are embedded as `data:` URLs before Chromium renders the PDF.
- Absolute paths, `file:` URLs, parent-directory escapes, missing files, and
  over-limit images are not passed to Chromium as live file reads.
- Relative filesystem links remain visible text but are not exported as local
  `file:` annotations that reveal the producer's filesystem layout.
- Blocked or missing images render as visible placeholders, so authors can see
  what was skipped.

### Project configuration

`mardas.toml` is a trusted local project input. The CLI discovers the nearest file
from the Markdown directory upward unless `--config` selects a specific file or
`--no-config` disables discovery. Relative paths are resolved from the configuration
directory. Project files are bounded to 1 MiB. Oversized files, unknown sections,
unknown keys, unsupported schema versions, invalid values, and missing configured
assets are rejected before Chromium starts.

Project configuration can explicitly enable `security.unsafe_html` or
`security.allow_remote_assets`. Both settings expand the trust boundary and are
reported by `mrs-md2pdf validate` and `mrs-md2pdf doctor` as stable warning
diagnostics. Keep both disabled for untrusted documents and reproducible offline
builds. Command-line safety overrides such as `--safe-html` and
`--block-remote-assets` take precedence over the project file.

### Remote assets

Remote `http(s)` image assets are blocked by default for privacy,
reproducibility, and offline builds. Use `--allow-remote-assets` only for trusted
documents that intentionally fetch network images. Studio Fast Preview does not
fetch remote or local image paths and disables unsafe or filesystem link schemes;
PDF-like Preview and export remain the authoritative renderer-backed paths.

### Raw HTML

Raw HTML is sanitized by default. The sanitizer removes active content, event
handlers, unsafe URL schemes, style/script injection, iframes, and non-raster
`data:` images. `--unsafe-html` disables this boundary and should be used only
for documents you fully trust.

### MathJax and Mermaid

MathJax is vendored locally so formula rendering does not require a CDN. Mermaid
flowcharts are rendered by the built-in offline subset renderer. Unsupported
Mermaid features may be simplified rather than executed by a browser-side
runtime.

## Studio / GUI boundary

`mrs-md2pdf-gui` is intended for local use. The backend enforces Markdown and
asset size limits and validates render options before calling the renderer. When
binding Studio to a non-local host, remember that reachable users can submit
Markdown and attached assets. Use host-level access controls or a private network
if you expose it beyond `127.0.0.1`.

Studio render endpoints accept only JSON requests from the active Studio page:
the local browser session receives a per-run API token, and `/api/render` plus
`/api/render-html` reject untrusted Host/Origin headers, cross-site Fetch
Metadata, missing tokens, malformed or unbounded request bodies, and non-JSON
media types before rendering begins. Preview freshness is isolated per browser
tab, and PDF exports are concurrency-bounded so repeated clients cannot launch an
unlimited number of Chromium jobs.

Studio exports use a bounded worker pool and queue. Workers may keep Chromium alive for a configured idle period, but every export runs in a new browser context so cookies, DOM state, object URLs, and page storage do not cross document boundaries. A renderer failure or disconnected browser causes that worker to discard the browser before accepting the next job.

Completed export artifacts are regular files inside a per-job private temporary directory, have a bounded maximum size and retention period, and are streamed to the browser instead of being copied into one large server-memory buffer. Paths returned by a worker are validated before download. Queue-full, cancelled, expired, and failed jobs use stable client-facing codes without exposing temporary paths or exception details.

Cancellation is cooperative. It is checked before parsing, before browser startup, between cover/content rendering, and before PDF post-processing. Chromium's active `page.pdf()` operation is not force-killed mid-call because the process may be shared by the worker; cancellation completes at the next safe checkpoint.

### Studio Project Workspace

`mrs-md2pdf-gui --project PATH` explicitly grants the local Studio process access to the `mardas.toml` project rooted at `PATH`. The Project Explorer exposes only supported UTF-8 text files below that resolved project root. Hidden/generated directories, unsupported extensions, absolute paths, parent escapes, symbolic links, non-regular files, and files larger than 4 MiB are not editable through the API.

Project file reads and writes require the same per-run Studio token and Host/Origin checks as render requests. A save must include the SHA-256 hash returned when the file was opened; if another tool changes the file first, Studio returns a conflict instead of overwriting the external edit. Successful writes use a sibling temporary file, flush it, preserve the original mode, and atomically replace the target. Diagnostic paths returned to the browser are project-relative and do not expose host paths outside the workspace. Book preview and export validate the saved project and retain the existing project-root, bibliography, cross-reference, citation, and output-integrity boundaries.

The portable `.mardas.json` Studio bundle workflow is separate from Project Workspace mode. Loading a bundle does not grant arbitrary filesystem access, and live project editing is never enabled merely by opening the normal Studio page.

## Desktop sidecar boundary

`mrs-md2pdf-sidecar` is the process boundary for future native desktop clients. It opens no network listener and accepts bounded newline-delimited JSON-RPC requests from `stdin`. Protocol output is written exclusively to `stdout`; logs and tracebacks remain on `stderr`. Requests larger than 8 MiB, unknown methods, unknown parameters, invalid option names, concurrent render attempts, and malformed JSON are rejected with stable error codes.

Only one render/preview/validation job is active at a time. Cancellation is cooperative and uses the renderer's existing safe checkpoints; it does not kill a shared Chromium process mid-write. The desktop parent process is responsible for spawning the sidecar with private pipes, validating the ready/health protocol version, and terminating the child process during application shutdown.

Standalone runtime archives contain a flat top-level application directory and an internal SHA-256 inventory. Release verification rejects path traversal, duplicate entries, symbolic links, missing or extra files, digest mismatches, missing sidecar executables, protocol/version mismatches, and runtimes that do not include pinned Chromium. The runtime manifest is integrity evidence, not a digital signature; users should also verify release checksums and GitHub attestations.

## Output integrity

The CLI rejects input, PDF output, and debug-HTML paths that resolve to the same
file, including symlink and hardlink aliases. Final PDF and debug-HTML files are
written to sibling temporary files and atomically replaced only after a complete
successful write, so an interrupted post-processing step does not truncate a
previous valid artifact.

Front matter is parsed with bounded depth, node count, and scalar size. Recursive
YAML aliases and malformed YAML are rejected with controlled diagnostics rather
than being silently ignored or expanded without limits.

## Multi-file Book Mode boundaries

Book chapter paths are trusted project declarations but remain constrained to the directory containing `mardas.toml`. Absolute chapter paths, parent-directory escapes, symlink escapes, duplicate source files, source/output collisions, and unsupported Markdown extensions are rejected before Chromium starts.

Each chapter resolves relative assets from its own directory while the allowed containment boundary is the project root. This supports shared directories such as `assets/` without permitting arbitrary host-file reads. Chapter IDs are namespaced before assembly, and only relative links to another listed chapter are restored as internal PDF links; unrelated local filesystem links remain inert.

## Chromium sandboxing

The CLI option `--chromium-sandbox` controls Chromium sandbox behavior:

- `auto` keeps Chromium sandboxing enabled for normal users and disables it only
  when the process is running as root, where Chromium commonly requires
  `--no-sandbox` in containers.
- `on` always requests sandboxed Chromium.
- `off` passes `--no-sandbox` and should be used only inside trusted containers,
  disposable environments, or isolated CI jobs.

## PDF metadata and reproducibility

Guide/example builds honor `SOURCE_DATE_EPOCH` so repeated release builds do not
churn PDF metadata timestamps. User-generated PDFs may still include author,
title, keyword, and date metadata from front matter; avoid placing sensitive data
in front matter when producing public PDFs.

## Cross-reference and numbering boundary

Semantic labels such as `{#fig:model}` and reference tokens such as `@fig:model` are document-internal identifiers. They do not resolve filesystem paths, fetch URLs, execute code, or weaken the existing Markdown image, safe-HTML, Book Mode project-root, and remote-asset policies. The renderer accepts only the supported `fig`, `tbl`, `eq`, and `lst` kinds with bounded ASCII label names.

Duplicate labels, unresolved references, kind mismatches, malformed labels, and ambiguous multiple-label markers are rejected before Chromium starts. References inside code, existing links, scripts, styles, and other literal contexts are not expanded. Generated reference lists contain only sanitized text and internal `#xref-*` destinations derived from validated labels.

## Bibliography and citation boundary

Bibliography sources are local project inputs. Project/front-matter paths must remain inside the document or project root after symlink resolution, use `.bib` or `.json`, and stay within bounded source-count, file-size, and entry-count limits. Output PDF and debug HTML paths cannot alias a bibliography source.

Citation rendering never performs DOI lookup, URL retrieval, or remote metadata discovery. DOI and URL fields may become ordinary `https` links in the final bibliography, but they are not fetched during conversion. Citation keys are validated internal identifiers; duplicate keys, malformed sources/groups, repeated source files, and undefined citations fail before Chromium starts. Citation-like text in code, existing links, scripts, styles, and literal contexts remains unchanged.

## Release supply-chain boundary

Release metadata is generated from files already produced by the release gate and from the dependency closure installed in a clean wheel environment. The SPDX generator records exact installed runtime versions and release-artifact digests; it does not execute package code or contact metadata services.

`RELEASE-MANIFEST.json` and `CHECKSUMS.sha256` use flat relative filenames only. Verification rejects absolute paths, parent traversal, duplicate names, symlinks, unlisted files, missing files, oversized artifacts, and digest mismatches. Offline bundle verification applies the same restrictions to ZIP members and rejects symlink entries or checksum inventories that reference files outside the archive root.

The offline bundle installer verifies all embedded files before creating a virtual environment and installs only from its local wheelhouse with `--no-index`. It does not claim to include Chromium or a Python runtime. A tampered extracted bundle must be treated as untrusted even when the original GitHub artifact had a valid attestation.

GitHub release provenance uses short-lived OIDC/Sigstore signing through `actions/attest`; no long-lived signing key is stored in the repository. The manifest-governed release payload and the post-finalization Sigstore bundles are uploaded separately, and each has its own checksum inventory. Attestations prove which workflow and source revision produced an artifact, but they do not replace checksum verification, source review, dependency review, or an explicit maintainer release decision.

## Reporting issues

For security-related issues, use a private report when available. Share minimal
reproduction steps and avoid attaching confidential documents. Include whether
`--unsafe-html`, `--allow-remote-assets`, custom branding assets, or non-local
Studio binding were used.

## Accessibility and archival audit boundaries

The accessibility commands analyze trusted local project text and generated PDF structure without sending content to a network service:

```bash
mrs-md2pdf audit-accessibility document.md
mrs-md2pdf audit-book-accessibility path/to/book
mrs-md2pdf audit-pdf output.pdf --profile all
```

Source audits are bounded by the existing Markdown, configuration, bibliography, and Book Mode limits. PDF audit opens only the explicitly supplied local file and reports metadata, fonts, tagging signals, actions, attachments, and archival indicators. Audit output avoids claiming PDF/UA, WCAG, or PDF/A conformance. A structure tree, output intent, or PDF/A identifier must never be fabricated merely to silence an audit; formal compliance requires an independent validator and manual review.

Generated PDFs declare a catalog language when the source or project declares one, include XMP/document metadata, and request display of the document title. They do not currently claim a verified tagged-PDF structure. Treat `audit-pdf` as a readiness and risk report rather than a certification tool.

## Native desktop shell boundary

Mardas Studio does not expose the rendering engine through localhost. The Tauri process starts the bundled sidecar with piped standard input/output, forwards only versioned JSON-RPC methods, emits progress as application events, and terminates the child during application shutdown. Operational logs remain separate from protocol output.

Native open/save dialogs are the primary source of document paths. Open/reveal actions canonicalize an existing path and launch fixed operating-system commands without interpolating a shell command. The installer build accepts only a standalone runtime whose manifest version, browser flag, file inventory, sizes, and SHA-256 digests all verify. The staged runtime and generated frontend are build inputs and are not accepted from arbitrary user-controlled directories during normal application use.
