import test from "node:test";
import assert from "node:assert/strict";
import {
  closeDocument,
  createDocument,
  documentDirty,
  findDocumentByPath,
  findSavePathCollision,
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

test("a completed save never overwrites edits made while the request was in flight", () => {
  const document = createDocument({ path: "/report.md", content: "A", revision: "r1" });
  updateDocumentContent(document, "B");
  markDocumentSaved(document, { path: "/report.md", revision: "r2", read_only: false }, "A");
  assert.equal(document.content, "B");
  assert.equal(document.savedContent, "A");
  assert.equal(documentDirty(document), true);
  assert.equal(document.contentVersion, 1);
});

test("new untitled documents stay dirty until their first successful save", () => {
  const document = createDocument({ content: "# New" });
  assert.equal(documentDirty(document), true);
  markDocumentSaved(document, { path: "/new.md", revision: "r1", read_only: false }, "# New");
  assert.equal(documentDirty(document), false);
});

test("path lookup is slash and case tolerant", () => {
  const document = createDocument({ path: "C:\\Docs\\Report.md", content: "" });
  assert.equal(findDocumentByPath([document], "c:/docs/report.md"), document);
});

test("POSIX files that differ only by case remain distinct", () => {
  const upper = createDocument({ path: "/Docs/A.md" });
  const lower = createDocument({ path: "/Docs/a.md" });
  assert.equal(findDocumentByPath([upper, lower], "/Docs/A.md"), upper);
  assert.equal(findDocumentByPath([upper, lower], "/Docs/a.md"), lower);
});

test("Save As detects another open model before it can overwrite the path", () => {
  const source = createDocument({ path: "/docs/source.md" });
  const target = createDocument({ path: "/docs/target.md" });
  assert.equal(findSavePathCollision([source, target], source, "/docs/target.md"), target);
  assert.equal(findSavePathCollision([source, target], source, "/docs/source.md"), null);
});

test("closing a tab selects a neighboring document", () => {
  const first = createDocument({ path: "/a.md" });
  const second = createDocument({ path: "/b.md" });
  const result = closeDocument([first, second], first.id);
  assert.deepEqual(result.documents, [second]);
  assert.equal(result.nextId, second.id);
});
