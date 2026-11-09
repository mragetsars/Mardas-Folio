import test from "node:test";
import assert from "node:assert/strict";
import { resetProjectSession } from "../frontend/js/core/project-lifecycle.mjs";

test("closing a project detaches open documents but keeps their buffers and dirty edits", () => {
  const project = { path: "/books/novel", book: { enabled: true } };
  const chapter = {
    path: "/books/novel/chapters/one.md",
    content: "unsaved chapter edit",
    savedContent: "saved chapter",
    projectPath: project.path,
    projectRelativePath: "chapters/one.md",
    projectSha256: "revision",
  };
  const state = {
    project,
    documents: [chapter],
    projectGeneration: 4,
    projectRequestSequence: 7,
    projectSearchSequence: 2,
    activeProjectSearchRequestId: "search-1",
    projectFileRequests: new Map([["4:chapters/one.md", Promise.resolve()] ]),
    projectDiagnostics: [{ code: "BOOK" }],
    bibliographyEntries: [{ id: "ref" }],
    bibliographySequence: 3,
    assetSequence: 5,
    validationSequence: 8,
    previewSequence: 11,
    documentActivationSequence: 12,
    bookOutputPath: "/books/novel/dist/book.pdf",
  };

  assert.equal(resetProjectSession(state), project);

  assert.equal(state.project, null);
  assert.equal(state.projectGeneration, 5);
  assert.equal(state.projectRequestSequence, 8);
  assert.equal(state.projectSearchSequence, 3);
  assert.equal(state.activeProjectSearchRequestId, null);
  assert.equal(state.projectFileRequests.size, 0);
  assert.deepEqual(state.projectDiagnostics, []);
  assert.deepEqual(state.bibliographyEntries, []);
  assert.equal(state.bookOutputPath, null);
  assert.equal(state.documents.length, 1);
  assert.equal(chapter.content, "unsaved chapter edit");
  assert.equal(chapter.savedContent, "saved chapter");
  assert.equal(chapter.path, "/books/novel/chapters/one.md");
  assert.equal("projectPath" in chapter, false);
  assert.equal("projectRelativePath" in chapter, false);
  assert.equal("projectSha256" in chapter, false);
});

test("closing an empty project session is safe and still invalidates stale requests", () => {
  const state = { documents: [], projectGeneration: 0, projectRequestSequence: 0 };
  assert.equal(resetProjectSession(state), null);
  assert.equal(state.projectGeneration, 1);
  assert.equal(state.projectRequestSequence, 1);
});
