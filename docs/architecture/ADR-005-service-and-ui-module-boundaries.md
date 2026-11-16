# ADR-005: Extract services and UI components behind stable boundaries

- **Status:** Accepted
- **Date:** 2026-11-11
- **Updated:** 2026-11-16

## Context

The application facade combined request validation, publishing configuration,
document storage, asset operations and use-case dispatch. The desktop entrypoint
also constructed every export-option control and held its draft and search state.
Tests often patched internals in these large modules or matched their source text.

## Decision

Extract cohesive Python modules for errors, request validation, render requests,
document storage, and assets. Keep the existing application API as explicit
re-exports. Share the atomic file writer between the document and project services;
policy, locking and final revision checks remain with their callers.

Publication options, exceptions and page-size validation also live outside the
browser renderer. Configuration can be imported without loading Markdown, PDF or
Playwright packages. Static print CSS lives in a packaged stylesheet; a small
composer supplies dynamic page variables. The renderer retains compatibility
exports and owns execution, not the definitions needed to validate a request.

Extract the export settings panel as an instance with private draft state and
injected translation, preset lookup, native picker and notification callbacks.
Keep reusable SVG and radio-group behavior in UI primitives. The entrypoint
composes these pieces and handles preview scheduling and export status.

Test leaf-module dependency direction, public workflows and real DOM interactions.
Expand the type and critical-coverage scopes to follow moved code. Use isolated
fixtures with teardown instead of success-path cleanup at the end of each test.

## Consequences

- Existing protocol methods, error identities and public application functions
  remain available. No protocol version bump or data migration is required.
- Tests that inject internal failures patch the module that owns that operation;
  public behavior tests continue through `EngineService`.
- New file operations reuse one commit implementation. Browser components can be
  exercised without starting Tauri or rendering a PDF.
- This does not change Chromium's publishing algorithm or replace the desktop
  framework. Other large modules should be decomposed at tested domain boundaries
  when their responsibilities are changed, with the same compatibility discipline.

Implementation and testing rules are in [Engineering](../ENGINEERING.md).
The [engineering review](../ENGINEERING_REVIEW.fa.md) records validation evidence
and the remaining boundaries for future work.
