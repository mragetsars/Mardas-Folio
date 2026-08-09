# ADR-004: Use Tauri as the native desktop shell

- Status: Accepted
- Date: 2026-07-30
- Applies to: Mardas Folio 1.24 and later

## Context

The publishing engine is Python/Playwright and the versioned sidecar already exposes a bounded JSON-RPC protocol over standard streams. The browser-based Studio remains useful for advanced workflows, but requiring users to install Python, install Chromium, launch a localhost server, and work in an external browser is not an acceptable final-product experience.

## Decision

Mardas Folio uses a Tauri 2 shell. The packaged application embeds the complete verified PyInstaller `onedir` runtime as a resource and launches `mardas-sidecar` directly with piped stdin/stdout. The frontend is a static ES-module application with a locally bundled CodeMirror 6 editor. Locked npm dependencies are used only to reproduce and check the committed editor bundle; the installed application loads no editor code from a CDN or network. The complete frontend is built to a deterministic file inventory before Tauri compilation.

The shell provides:

- one native application instance;
- native Markdown open and PDF save dialogs;
- `.md` and `.markdown` file associations;
- window-state persistence;
- structured sidecar request, progress, cancellation, and shutdown handling;
- fixed operating-system open/reveal actions;
- no external browser launch and no localhost application server.

The Windows artifact is an NSIS setup executable. The installer stages only a standalone runtime whose manifest version, file inventory, sizes, hashes, and bundled-browser flag verify.

## Consequences

The Python renderer remains the source of truth and does not need to be rewritten. Rust, Node.js, and Tauri are release-toolchain dependencies, not end-user prerequisites. Start Center, Quick Export, multi-document authoring, project/book workflows, and CodeMirror editing all use the same versioned application-service contract.

A Tauri/Rust build cannot be fully validated on a machine without the Rust toolchain. Windows CI is therefore the authoritative compile, runtime-embedding, Unicode-render, and NSIS verification environment.
