# ADR-003: Frozen standalone rendering runtime

- **Status:** Accepted
- **Date:** 2026-07-30

## Decision

The first end-user runtime is a PyInstaller `onedir` bundle containing:

- the Python interpreter and Mardas package;
- Playwright driver resources;
- the exact Chromium/headless-shell archive used by the installed Playwright version;
- package CSS, GUI assets, and vendored MathJax;
- a SHA-256 `runtime-manifest.json`.

The build is platform-native: Windows artifacts are built on Windows runners. The initial release target is Windows x64; macOS and Linux desktop packaging remain later product phases.

## Why `onedir`

`onedir` avoids extracting a large browser/runtime archive on every launch, improves startup predictability, and makes antivirus, diagnostics, and update deltas easier to reason about. The eventual installer can still present one normal application to the user.

## Browser rule

Production standalone artifacts must include their pinned browser. Falling back to an arbitrary user-installed Chrome is not allowed for release verification. `--allow-missing-chromium` exists only for protocol/build tests and cannot pass standalone release verification.
