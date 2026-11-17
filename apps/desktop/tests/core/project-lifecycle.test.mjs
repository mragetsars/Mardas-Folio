import test from "node:test";
import assert from "node:assert/strict";
import {
  resetProjectSession,
  applyProjectSession,
  attachProjectMembership,
} from "../../frontend/js/core/project-lifecycle.mjs";

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
    projectFileRequests: new Map([["4:chapters/one.md", Promise.resolve()]]),
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

test("a refreshed manifest reattaches files without changing dirty buffers or read revisions", () => {
  const hash = "a".repeat(64);
  const chapter = {
    path: "C:\\Books\\Thesis\\one.md",
    content: "Unsaved edits",
    savedContent: "Original",
    revision: "old:" + hash,
    projectPath: "/old",
    projectRelativePath: "old.md",
    projectSha256: "old",
  };
  const unrelated = {
    path: "C:/Books/Thesis-extra/one.md",
    content: "Outside",
    projectPath: "/old",
    projectRelativePath: "old.md",
    projectSha256: "old",
  };
  const state = {
    documents: [chapter, unrelated],
    projectGeneration: 2,
    bibliographySequence: 3,
    assetSequence: 4,
    validationSequence: 5,
    previewSequence: 6,
  };
  const project = {
    path: "c:/books/thesis/",
    files: [{ path: "one.md", sha256: "new-disk-hash" }],
    diagnostics: [{ severity: "warning", message: "Title missing" }],
  };
  applyProjectSession(state, project);
  assert.equal(state.project, project);
  assert.deepEqual(
    [
      state.projectGeneration,
      state.bibliographySequence,
      state.assetSequence,
      state.validationSequence,
      state.previewSequence,
    ],
    [3, 4, 5, 6, 7],
  );
  assert.deepEqual(state.projectDiagnostics, project.diagnostics);
  assert.equal(chapter.content, "Unsaved edits");
  assert.equal(chapter.savedContent, "Original");
  assert.equal(chapter.revision, "old:" + hash);
  assert.equal(chapter.projectPath, project.path);
  assert.equal(chapter.projectRelativePath, "one.md");
  assert.equal(chapter.projectSha256, hash);
  assert.equal(unrelated.projectPath, undefined);
  assert.equal(unrelated.projectRelativePath, undefined);
  assert.equal(unrelated.projectSha256, undefined);
  assert.equal(unrelated.content, "Outside");
});

test("membership removal leaves drafts intact and never invents an optimistic revision", () => {
  const draft = { content: "Draft", projectPath: "/old", projectRelativePath: "old.md" };
  attachProjectMembership(draft, { path: "/book", files: [] });
  assert.deepEqual(draft, { content: "Draft" });
  const document = { path: "/book/one.md", revision: null };
  attachProjectMembership(document, {
    path: "/book",
    files: [{ path: "one.md", sha256: "disk-hash" }],
  });
  assert.equal(document.projectSha256, "");
  attachProjectMembership(document, null);
  assert.equal(document.projectPath, undefined);
});
