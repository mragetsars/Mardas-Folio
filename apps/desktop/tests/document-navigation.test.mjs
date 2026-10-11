import test from "node:test";
import assert from "node:assert/strict";
import { createDocument } from "../frontend/js/core/documents.mjs";
import { documentNavigationEntries, filterNavigationEntries } from "../frontend/js/core/document-navigation.mjs";

test("file picker includes unsaved buffers and disambiguates identical filenames by path", () => {
  const first = createDocument({ path: "/draft/report.md", content: "A" });
  const second = createDocument({ path: "/final/report.md", content: "B" });
  const draft = createDocument();
  const entries = documentNavigationEntries([first, second, draft]);
  assert.equal(entries[2].dirty, true);
  assert.equal(filterNavigationEntries(entries, "report final")[0].documentId, second.id);
  assert.equal(filterNavigationEntries(entries, "draft report")[0].documentId, first.id);
  assert.equal(filterNavigationEntries(entries, "absent").length, 0);
});

test("open Windows buffers replace project disk entries without dropping closed files", () => {
  const open = createDocument({ path: "C:\\Notes\\Chapter.md" });
  const entries = documentNavigationEntries([open], { path: "c:/notes", files: [
    { path: "chapter.md", kind: "markdown" }, { path: "next.md", kind: "markdown" },
    { path: "image.png", kind: "image" },
  ] });
  assert.equal(entries.length, 2);
  assert.equal(entries[1].relativePath, "next.md");
});

test("Persian titles can be found with Arabic keyboard variants and multiword queries", () => {
  const entries = [{ id: "a", label: "یادداشت‌های پژوهش", detail: "/docs/طرح.md" }];
  assert.equal(filterNavigationEntries(entries, "يادداشت پژوهش")[0].id, "a");
  assert.equal(filterNavigationEntries(entries, "طرح پژوهش")[0].id, "a");
});
