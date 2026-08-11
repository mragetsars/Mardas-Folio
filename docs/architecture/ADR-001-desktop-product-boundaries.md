# ADR-001: Desktop product boundaries

- **Status:** Accepted
- **Date:** 2026-07-30

## Decision

Mardas Folio keeps the established Python renderer as the publishing engine and introduces a separate desktop boundary around it:

1. `mardas_folio` remains the renderer/core package.
2. `folio` remains the automation and power-user CLI.
3. `folio-sidecar` is the versioned process boundary for desktop clients.
4. A future Tauri shell owns native windows, menus, file dialogs, updates, and application lifecycle.

The desktop shell must not import Python modules directly or expose the existing localhost Studio server. It communicates only through the sidecar contract.

## Rationale

The renderer already contains the difficult PDF, RTL/LTR, MathJax, Mermaid, citation, book, navigation, and audit behavior. Rewriting it in another language would create substantial regression risk. A process boundary lets the GUI evolve independently while preserving CLI compatibility and providing crash isolation.

## Consequences

- Python engine and desktop UI versions can evolve independently when the protocol remains compatible.
- The sidecar is single-job by design; the desktop application owns user-facing queues.
- The current browser-based Studio remains available during migration but is no longer the target product architecture.
