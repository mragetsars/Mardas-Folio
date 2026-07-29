import test from "node:test";
import assert from "node:assert/strict";
import {
  closeDocument,
  createDocument,
  documentDirty,
  findDocumentByPath,
  markDocumentSaved,
  updateDocumentContent,
} from "../frontend/js/core/documents.mjs";

test("document state tracks dirty and saved revisions", () => {
  const document = createDocument({ path: "C:\\Docs\\report.md", content: "# A", revision: "r1" });
  assert.equal(documentDirty(document), false);
  updateDocumentContent(document, "# B");
  assert.equal(documentDirty(document), true);
  markDocumentSaved(document, { path: "C:\\Docs\\report.md", revision: "r2", read_only: false });
  assert.equal(documentDirty(document), false);
  assert.equal(document.revision, "r2");
});

test("path lookup is slash and case tolerant", () => {
  const document = createDocument({ path: "C:\\Docs\\Report.md", content: "" });
  assert.equal(findDocumentByPath([document], "c:/docs/report.md"), document);
});

test("closing a tab selects a neighboring document", () => {
  const first = createDocument({ path: "/a.md" });
  const second = createDocument({ path: "/b.md" });
  const result = closeDocument([first, second], first.id);
  assert.deepEqual(result.documents, [second]);
  assert.equal(result.nextId, second.id);
});
