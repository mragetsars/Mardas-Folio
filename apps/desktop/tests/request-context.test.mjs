import test from "node:test";
import assert from "node:assert/strict";
import { createDocument, updateDocumentContent } from "../frontend/js/core/documents.mjs";
import {
  captureDocumentContext,
  captureProjectContext,
  documentContextCurrent,
  projectContextCurrent,
} from "../frontend/js/core/request-context.mjs";

test("document request contexts reject tab, content, path, and project changes", () => {
  const first = createDocument({ path: "/project/a.md", content: "A" });
  const second = createDocument({ path: "/project/b.md", content: "B" });
  const state = { documents: [first, second], activeDocumentId: first.id, projectPath: "/project" };
  const context = captureDocumentContext(first, state.projectPath);
  assert.equal(documentContextCurrent(context, state), true);

  state.activeDocumentId = second.id;
  assert.equal(documentContextCurrent(context, state), false);
  state.activeDocumentId = first.id;
  updateDocumentContent(first, "A2");
  assert.equal(documentContextCurrent(context, state), false);

  assert.equal(documentContextCurrent(context, state, { requireContent: false }), true);
  state.projectPath = "/other";
  assert.equal(documentContextCurrent(context, state, { requireContent: false }), false);
});

test("a late book response is rejected after switching from project A to project B", () => {
  const projectA = "C:\\Books\\A";
  const context = captureProjectContext(projectA, 4);
  const state = { projectPath: "C:\\Books\\B", projectGeneration: 5 };

  assert.equal(projectContextCurrent(context, state), false);
  assert.equal(
    projectContextCurrent(context, { projectPath: "c:/books/a", projectGeneration: 4 }),
    true,
  );
});
