# Mardas Folio Desktop

This directory contains the native desktop product shipped with Mardas Folio 1.31.

```text
frontend/       offline Start Center, Quick Export, and bundled CodeMirror workspace
src-tauri/      native Tauri shell and sidecar process manager
tests/          Node.js frontend contract tests
dist/           generated frontend output; never commit
```

Published packages target Windows 11 x86-64 (or Windows Server 2019+),
macOS 14+ on ARM64 and x86-64, and x86-64 Linux with Ubuntu 22.04 as the
release-tested baseline. Native runtimes and packages are built on their target
operating system; they are not cross-compiled release evidence.

## Product name and bundle identifier

The product is **Mardas Folio**: `productName`, `mainBinaryName`, every release
artifact (`Mardas-Folio-X.Y.Z-*`), the window title and the whole interface.

The bundle identifier deliberately still reads
`io.github.mragetsars.mardas-studio`. It is the key the updater matches an
installed application by, and the name of the per-user config and data
directory. Changing it would make every existing install look like a different
application: updates would stop arriving, and saved preferences, recent
documents and recovery snapshots would be orphaned. Renaming it is a migration,
not a rebrand, and needs its own change with a data-migration path.

Note that `tauri.conf.json` rejects unknown keys, so this rationale cannot live
in the file as a comment — `cargo check` fails on any extra field.

## Authoring workspace

The current 1.31 workspace provides a conflict-safe document lifecycle on top of the sidecar API:

- multiple Markdown tabs and saved-session restore;
- bounded local recovery snapshots for dirty buffers;
- atomic Markdown and supported-text saves with revision-based external-change detection;
- outline, top-level front-matter form, assets, citations, and diagnostics panels;
- literal find/replace and Markdown formatting commands;
- validation and sanitized preview of unsaved text without overwriting the source file.

The former textarea foundation is now replaced by CodeMirror 6 behind the editor adapter. The editor source is bundled deterministically into `frontend/js/vendor/`, committed with third-party notices, and loaded only from application resources; no CDN or runtime network dependency is used. PDF export remains authoritative for MathJax, Mermaid, pagination, and print fidelity.

## Local contract checks

```bash
npm --prefix apps/desktop ci --no-audit --no-fund
npm --prefix apps/desktop run check:editor
python scripts/build_desktop_frontend.py
python scripts/verify_desktop_frontend.py apps/desktop/dist
node --test apps/desktop/tests/*.test.mjs
python -m pytest -q tests/test_desktop_app.py
```

## Windows installer build

First build the frozen sidecar runtime with bundled Chromium. Then install Rust and Tauri CLI and run:

```powershell
cargo install tauri-cli --version 2.11.4 --locked
python scripts/build_desktop_app.py `
  --runtime build/standalone-runtime/Mardas-MD2PDF-X.Y.Z-runtime-windows-x86_64 `
  --clean
```

The checked-in `rust-toolchain.toml` pins Rust 1.97.1 and `Cargo.lock` pins the application graph. Both desktop builders pass `--locked`; update and review the lockfile explicitly whenever Rust dependencies change.

Do not commit `dist/`, `src-tauri/target/`, or staged files below `src-tauri/resources/sidecar/`.
