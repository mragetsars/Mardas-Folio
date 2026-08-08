# ADR-003: Frozen standalone rendering runtime

- **Status:** Accepted
- **Date:** 2026-07-30

## Decision

The first end-user runtime is a PyInstaller `onedir` bundle containing:

- the Python interpreter and Mardas package;
- Playwright driver resources;
- the exact Chromium/headless-shell archive used by the installed Playwright version;
- package CSS, GUI assets, and vendored MathJax;
- a schema-v2 SHA-256 `runtime-manifest.json` that distinguishes regular files from explicitly declared relative symbolic links.

Schema v2 preserves safe runtime links required by platform packages. Every path component is inspected without following links first; absolute or root-escaping targets, dangling links, cycles, excessive chains, traversal through links, and manifest/filesystem mismatches are rejected by build, staging, ZIP, provenance, and verification tooling. Legacy schema-v1 manifests remain accepted only for regular-file inventories.

The build is platform-native: Windows, macOS, and Linux artifacts must be built and tested on their corresponding release runners rather than treated as cross-compiled output.

## Why `onedir`

`onedir` avoids extracting a large browser/runtime archive on every launch, improves startup predictability, and makes antivirus, diagnostics, and update deltas easier to reason about. The eventual installer can still present one normal application to the user.

## Browser rule

Production standalone artifacts must include their pinned browser. Falling back to an arbitrary user-installed Chrome is not allowed for release verification. `--allow-missing-chromium` exists only for protocol/build tests and cannot pass standalone release verification.
