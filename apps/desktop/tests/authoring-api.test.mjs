import { installTauriFixture } from "./fixtures/tauri.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import {
  importDocumentAsset,
  previewDocumentText,
  readDocument,
  readTextDocument,
  resolveMarkdownLink,
  saveDocument,
  saveTextDocument,
  validateDocumentText,
} from "../frontend/js/adapters/authoring-api.mjs";

test("authoring API uses versioned sidecar methods", async (t) => {
  const { calls } = installTauriFixture(t);

  await readDocument("/doc.md");
  await readTextDocument("/config.toml");
  await saveDocument({ path: "/doc.md", content: "# x", expectedRevision: "r1" });
  await saveTextDocument({ path: "/config.toml", content: "title = 'x'" });
  await validateDocumentText({ path: "/doc.md", content: "# x" });
  await previewDocumentText({ path: "/doc.md", content: "# x" });
  await importDocumentAsset("/doc.md", "/image.png");
  await resolveMarkdownLink("/doc.md", "next.md#section", "/project");
  assert.deepEqual(calls.map((call) => call.args.method), [
    "document.read",
    "document.read_text",
    "document.save",
    "document.save_text",
    "validate.document_text",
    "preview.document_text",
    "document.import_asset",
    "document.resolve_markdown_link",
  ]);
  assert.equal(calls[2].args.params.expected_revision, "r1");
  assert.equal(calls[3].args.params.path, "/config.toml");
  assert.deepEqual(calls[7].args.params, {
    document_path: "/doc.md",
    href: "next.md#section",
    project_path: "/project",
  });
});
