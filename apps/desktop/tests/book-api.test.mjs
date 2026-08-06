import test from "node:test";
import assert from "node:assert/strict";
import {
  addBookChapter,
  createBookProject,
  duplicateBookChapter,
  removeBookChapter,
  reorderBookChapters,
  startBookExport,
  startBookPreview,
  startBookValidation,
} from "../frontend/js/core/book-api.mjs";

test("book API maps UI workflows to versioned sidecar methods", async () => {
  const calls = [];
  globalThis.__TAURI__ = {
    core: {
      invoke: async (command, args) => {
        calls.push({ command, args });
        return { ok: true };
      },
    },
    event: { listen: async () => () => {} },
  };

  await createBookProject({
    parentPath: "/books",
    folderName: "thesis",
    title: "Thesis",
    language: "en-US",
    direction: "ltr",
  });
  await addBookChapter({
    projectPath: "/books/thesis",
    title: "Methods",
    expectedConfigSha256: "a".repeat(64),
    position: 1,
  });
  await duplicateBookChapter({
    projectPath: "/books/thesis",
    relativePath: "chapters/02-methods.md",
    title: "Methods Copy",
    expectedConfigSha256: "b".repeat(64),
  });
  await reorderBookChapters({
    projectPath: "/books/thesis",
    orderedPaths: ["chapters/02-methods.md", "chapters/01-introduction.md"],
    expectedConfigSha256: "c".repeat(64),
  });
  await removeBookChapter({
    projectPath: "/books/thesis",
    relativePath: "chapters/02-methods.md",
    expectedConfigSha256: "d".repeat(64),
  });
  const validation = startBookValidation("/books/thesis");
  const preview = startBookPreview("/books/thesis");
  const exported = startBookExport({
    projectPath: "/books/thesis",
    outputPath: "/books/thesis/dist/book.pdf",
  });
  await Promise.all([validation.promise, preview.promise, exported.promise]);

  assert.deepEqual(
    calls.map((call) => call.args.method),
    [
      "book.create",
      "book.add_chapter",
      "book.duplicate_chapter",
      "book.reorder_chapters",
      "book.remove_chapter",
      "book.validate",
      "book.preview",
      "book.export",
    ],
  );
  assert.equal(calls[0].args.params.folder_name, "thesis");
  assert.equal(calls[1].args.params.position, 1);
  assert.deepEqual(calls[3].args.params.ordered_paths, [
    "chapters/02-methods.md",
    "chapters/01-introduction.md",
  ]);
  assert.match(validation.requestId, /^book-validate-/);
  assert.match(preview.requestId, /^book-preview-/);
  assert.match(exported.requestId, /^book-export-/);
  delete globalThis.__TAURI__;
});

test("add chapter omits optional null payload fields", async () => {
  let captured;
  globalThis.__TAURI__ = {
    core: {
      invoke: async (_command, args) => {
        captured = args.params;
        return { ok: true };
      },
    },
    event: { listen: async () => () => {} },
  };
  await addBookChapter({
    projectPath: "/book",
    title: "Chapter",
    expectedConfigSha256: "hash",
  });
  assert.equal("position" in captured, false);
  assert.equal("content" in captured, false);
  delete globalThis.__TAURI__;
});
