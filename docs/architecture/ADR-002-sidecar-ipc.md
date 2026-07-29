# ADR-002: Versioned sidecar IPC over standard streams

- **Status:** Accepted
- **Date:** 2026-07-30

## Decision

The desktop process communicates with the rendering engine through newline-delimited JSON-RPC 2.0 over `stdin` and `stdout`.

- Protocol name: `mardas-sidecar`
- Protocol version: `1`
- Engine API version: `1.0.0`
- Maximum request line: 8 MiB
- Maximum active rendering job: one
- Logs: `stderr` only
- Structured messages: `stdout` only

The schemas in `schemas/sidecar/v1/` define the stable envelope. `system.capabilities` advertises available methods and render options. Long operations publish `job.progress` notifications and can be interrupted through `job.cancel`.

## Rationale

Standard streams avoid localhost ports, browser-origin concerns, port collisions, and firewall prompts. They also make child-process lifecycle, cancellation, test fixtures, and Tauri sidecar integration explicit.

## Compatibility rule

Adding optional result fields or methods is backward compatible. Removing or changing required fields requires a new protocol version. Desktop clients must call `system.health` and compare the protocol and engine API versions before submitting work.
