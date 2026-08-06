# Mardas sidecar protocol v1

The sidecar implements JSON-RPC 2.0, reads one UTF-8 request per line from `stdin`, and writes one JSON message per line to `stdout`. Clients must continue reading notifications until they receive a response with the matching request `id`.

## Lifecycle

```json
{"jsonrpc":"2.0","method":"system.ready","params":{"protocol":"mardas-sidecar","protocol_version":1,"engine_version":"1.26.0","pid":1234}}
```

Recommended startup sequence:

1. Start `mardas-sidecar` with piped standard streams.
2. Wait for `system.ready`.
3. Call `system.health`.
4. Call `system.capabilities` and verify supported methods.
5. Submit one render/preview/validation operation at a time.
6. Call `system.shutdown` before terminating the process.

## Document authoring lifecycle

The native authoring workspace uses revision-aware document operations. `document.read` returns UTF-8 content and a revision token. `document.save` writes atomically and rejects a stale `expected_revision` with `MARDAS-DOCUMENT-CONFLICT` unless the user explicitly requests a forced overwrite.

```json
{"jsonrpc":"2.0","id":"read-1","method":"document.read","params":{"path":"C:/work/doc.md"}}
```

```json
{"jsonrpc":"2.0","id":"save-1","method":"document.save","params":{"path":"C:/work/doc.md","content":"# Edited\n","expected_revision":"<revision>","force":false}}
```

Dirty buffers are validated or previewed without first changing the source file:

```json
{"jsonrpc":"2.0","id":"preview-1","method":"preview.document_text","params":{"input_path":"C:/work/doc.md","content":"# Unsaved edit\n","discover_config":true,"options":{}}}
```

Local authoring assets are enumerated with `document.list_assets` and imported through `document.import_asset`. Imports are size- and extension-bounded, reject symbolic-link sources/directories, and use atomic writes below the document's `assets/` directory.


## Project workspace lifecycle

The native project workspace opens only a directory containing a valid `mardas.toml`. Project operations remain bounded to that root, reject hidden/generated or symbolic-link paths, and return structured application errors.

```json
{"jsonrpc":"2.0","id":"project-1","method":"project.open","params":{"path":"C:/work/book"}}
```

```json
{"jsonrpc":"2.0","id":"search-1","method":"project.search","params":{"project_path":"C:/work/book","query":"method","regex":false,"case_sensitive":false,"max_results":200}}
```

Configured local bibliography sources are exposed through one read-only index shared by the desktop search panel and citation insertion:

```json
{"jsonrpc":"2.0","id":"bib-1","method":"bibliography.index","params":{"project_path":"C:/work/book","query":"smith","cited_keys":["smith2025"],"max_results":500}}
```

`preview.document_text` includes a `source_map` array for Markdown headings. Each item contains the rendered heading `id`, one-based source `line`, heading `level`, and plain `title`, allowing preview navigation without matching duplicate heading text.

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

- `document.read`
- `document.save`
- `document.list_assets`
- `document.import_asset`
- `project.open`
- `project.refresh`
- `project.read`
- `project.save`
- `project.search`
- `bibliography.index`
- `render.document`
- `render.book`
- `preview.document`
- `preview.document_text`
- `validate.document`
- `validate.document_text`
- `validate.book`
- `job.cancel`
- `system.health`
- `system.capabilities`
- `system.shutdown`

Unknown render options and unknown method parameters are rejected rather than ignored.
