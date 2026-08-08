# Project Documentation

This directory uses a **guide-first documentation model**. The English and Persian guides are the complete user manuals, the feature references, and the live renderer samples. They teach the feature, show runnable Markdown examples, and are rebuilt into the official PDFs under `examples/`.

Feature documentation is intentionally **not** split into separate reference pages. Earlier standalone feature notes were retired because they duplicated the guides and created drift. Keep user-facing explanations in the guides, and keep this directory focused on operations, release discipline, security, and documentation policy.

## Canonical user guides

- [English guide](./guides/GUIDE.en.md) — complete English user manual and live rendering sample.
- [راهنمای فارسی](./guides/GUIDE.fa.md) — complete Persian user manual and RTL/Persian live rendering sample.

Generated PDF versions are stored in:

- `examples/GUIDE.en.pdf`
- `examples/GUIDE.fa.pdf`

## Operations and governance

- [Changelog](./CHANGELOG.md) — version-by-version release ledger.
- [Release checklist](./RELEASE.md) — release gate, build, tag, and artifact workflow.
- [Maintenance workflow](./MAINTENANCE.md) — routine local checks, guide builds, distribution builds, and patch hygiene.
- [Security policy](./SECURITY.md) — trust boundaries for Markdown, HTML, assets, Studio, Chromium, and PDF metadata.
- [Native distribution](./DISTRIBUTION.md) — Windows/macOS/Linux package contracts and clean-machine release boundary.
- [Desktop update readiness](./UPDATES.md) — signed updater metadata, key handling, and activation gates.
- [Documentation system](./DOCUMENTATION.md) — ownership rules for guides, operations docs, changelog entries, and generated examples.
- [Architecture decisions](./architecture/) — accepted desktop product boundaries, sidecar protocol, and frozen-runtime design:
  - [Desktop product boundaries](./architecture/ADR-001-desktop-product-boundaries.md)
  - [Sidecar IPC](./architecture/ADR-002-sidecar-ipc.md)
  - [Frozen runtime](./architecture/ADR-003-frozen-runtime.md)
  - [Sidecar protocol v1](./architecture/SIDECAR-PROTOCOL-v1.md)

## Rule of thumb

When writing for users, update `docs/guides/GUIDE.en.md` and `docs/guides/GUIDE.fa.md`. When documenting a release gate, maintenance command, security boundary, or documentation policy, update the appropriate operations file above. Do not create a parallel feature manual under `docs/`.
