import test from "node:test";
import assert from "node:assert/strict";
import {
  importDocumentAsset,
  previewDocumentText,
  readDocument,
  readTextDocument,
  saveDocument,
  saveTextDocument,
  validateDocumentText,
} from "../frontend/js/core/authoring-api.mjs";

test("authoring API uses versioned sidecar methods", async () => {
  const calls = [];
  globalThis.__TAURI__ = {
    core: { invoke: async (command, args) => { calls.push({ command, args }); return { ok: true }; } },
    event: { listen: async () => () => {} },
  };
  await readDocument("/doc.md");
  await readTextDocument("/config.toml");
  await saveDocument({ path: "/doc.md", content: "# x", expectedRevision: "r1" });
  await saveTextDocument({ path: "/config.toml", content: "title = 'x'" });
  await validateDocumentText({ path: "/doc.md", content: "# x" });
  await previewDocumentText({ path: "/doc.md", content: "# x" });
  await importDocumentAsset("/doc.md", "/image.png");
  assert.deepEqual(calls.map((call) => call.args.method), [
    "document.read",
    "document.read_text",
    "document.save",
    "document.save_text",
    "validate.document_text",
    "preview.document_text",
    "document.import_asset",
  ]);
  assert.equal(calls[2].args.params.expected_revision, "r1");
  assert.equal(calls[3].args.params.path, "/config.toml");
  delete globalThis.__TAURI__;
});
