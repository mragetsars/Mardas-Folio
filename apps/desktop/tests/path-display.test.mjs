import test from "node:test";
import assert from "node:assert/strict";
import { compactDocumentLocation } from "../frontend/js/core/path-display.mjs";

test("locations preserve distinguishing folders without repeating a document filename", () => {
  assert.equal(compactDocumentLocation("E:\\Downloads\\Browser.Chrome\\README.md"), "Downloads / Browser.Chrome");
  assert.equal(compactDocumentLocation("/home/mrage/پروژه/فصل‌ها/یادداشت.md"), "پروژه / فصل‌ها");
  assert.equal(compactDocumentLocation("\\\\wsl.localhost\\Ubuntu\\home\\writer\\Codes\\Notes\\Mardas Folio\\README.md"), "Notes / Mardas Folio");
});

test("project-relative locations use path boundaries and Windows identity rules", () => {
  assert.equal(compactDocumentLocation("C:\\Work\\Book\\chapters\\one.md", { projectPath: "c:/work/book" }), "chapters");
  assert.equal(compactDocumentLocation("/work/book/chapter/one.md", { projectPath: "/work/book" }), "chapter");
  assert.equal(compactDocumentLocation("/work/book/one.md", { projectPath: "/work/book" }), "book");
  assert.equal(compactDocumentLocation("/work/book-two/chapters/one.md", { projectPath: "/work/book" }), "book-two / chapters");
});

test("extended Windows and UNC paths are display-normalized without mutating the input", () => {
  const source = "\\\\?\\C:\\Users\\mrage\\Documents\\note.md";
  assert.equal(compactDocumentLocation(source), "mrage / Documents");
  assert.equal(source, "\\\\?\\C:\\Users\\mrage\\Documents\\note.md");
  assert.equal(compactDocumentLocation("\\\\?\\UNC\\server\\share\\book\\chapter.md"), "share / book");
});

test("root-level files and unsaved documents retain meaningful fallback values", () => {
  assert.equal(compactDocumentLocation("C:\\note.md"), "C:/");
  assert.equal(compactDocumentLocation("/note.md"), "/");
  assert.equal(compactDocumentLocation("note.md"), "");
  assert.equal(compactDocumentLocation(null), "");
});
