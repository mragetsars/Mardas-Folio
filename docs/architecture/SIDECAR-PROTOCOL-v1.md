# Mardas sidecar protocol v1

The sidecar implements JSON-RPC 2.0, reads one UTF-8 request per line from `stdin`, and writes one JSON message per line to `stdout`. Clients must continue reading notifications until they receive a response with the matching request `id`.

## Lifecycle

```json
{"jsonrpc":"2.0","method":"system.ready","params":{"protocol":"mardas-sidecar","protocol_version":1,"engine_version":"1.23.0","pid":1234}}
```

Recommended startup sequence:

1. Start `mardas-sidecar` with piped standard streams.
2. Wait for `system.ready`.
3. Call `system.health`.
4. Call `system.capabilities` and verify supported methods.
5. Submit one render/preview/validation operation at a time.
6. Call `system.shutdown` before terminating the process.

## Document rendering

```json
{"jsonrpc":"2.0","id":"render-1","method":"render.document","params":{"input_path":"C:/work/doc.md","output_path":"C:/work/doc.pdf","discover_config":true,"options":{"toc":true,"quality_profile":"strict-publication"}}}
```

Progress notification:

```json
{"jsonrpc":"2.0","method":"job.progress","params":{"request_id":"render-1","sequence":1,"message":"Reading Markdown","fraction":0.03}}
```

Successful response:

```json
{"jsonrpc":"2.0","id":"render-1","result":{"output_path":"C:/work/doc.pdf","size_bytes":42000,"quality":{"ok":true}}}
```

## Cancellation

```json
{"jsonrpc":"2.0","id":"cancel-1","method":"job.cancel","params":{"request_id":"render-1"}}
```

Cancellation is cooperative. The engine checks the cancellation flag between renderer stages and returns error code `-32011` when the job stops.

## Supported application methods

- `render.document`
- `render.book`
- `preview.document`
- `validate.document`
- `validate.book`
- `job.cancel`
- `system.health`
- `system.capabilities`
- `system.shutdown`

Unknown render options and unknown method parameters are rejected rather than ignored.
