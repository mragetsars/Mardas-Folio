import test from "node:test";
import assert from "node:assert/strict";
import { createBookOperations } from "../../frontend/js/features/books/operations.mjs";
import {
  createDocument,
  markDocumentSaved,
  updateDocumentContent,
} from "../../frontend/js/core/documents.mjs";
import {
  captureProjectContext,
  projectContextCurrent,
} from "../../frontend/js/core/request-context.mjs";
import { installTauriFixture } from "../fixtures/tauri.mjs";

function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function setup(t, { invoke, confirm = async () => true, save } = {}) {
  const document = createDocument({ path: "/book/one.md", content: "# Saved" });
  const state = {
    project: { path: "/book", book: { output: "dist/book.pdf" } },
    projectGeneration: 1,
    documents: [document],
    bookRequestSequence: 0,
    projectDiagnostics: [],
  };
  const elements = new Map();
  const query = (selector) => {
    if (!elements.has(selector)) {
      const classes = new Set();
      const attributes = new Map();
      elements.set(selector, {
        dataset: {},
        disabled: selector === "#book-chapter-up",
        textContent: "",
        classList: {
          add: (name) => classes.add(name),
          toggle: (name, force) => (force ? classes.add(name) : classes.delete(name)),
          contains: (name) => classes.has(name),
        },
        setAttribute: (key, value) => attributes.set(key, value),
        removeAttribute: (key) => attributes.delete(key),
      });
    }
    return elements.get(selector);
  };
  const controls = [query("#book-validate"), query("#book-chapter-up")];
  const notices = [];
  const events = [];
  const native = installTauriFixture(t, {
    invoke: async (command, args) => {
      events.push(args?.method || command);
      if (invoke) return invoke(command, args, state);
      if (args?.method === "project.refresh") return state.project;
      return { ok: true, diagnostics: [] };
    },
  });
  const controller = createBookOperations({
    state,
    query,
    queryAll: (selector) => (selector.includes("button") ? controls : []),
    bookProject: () => state.project?.book,
    currentProjectContext: () =>
      captureProjectContext(state.project?.path, state.projectGeneration),
    projectContextIsCurrent: (context) =>
      projectContextCurrent(context, {
        projectPath: state.project?.path,
        projectGeneration: state.projectGeneration,
      }),
    applyProjectPayload: (project) => {
      state.project = project;
      state.projectGeneration += 1;
    },
    askConfirmation: async () => {
      events.push("confirm");
      return confirm();
    },
    saveDocument: async (model) => {
      events.push("save");
      if (save) return save(model);
      markDocumentSaved(model, { path: model.path }, model.content);
      return true;
    },
    refreshAuthoring: () => {},
    renderProblems: () => events.push("renderProblems"),
    activateSidebar: (name) => events.push("sidebar:" + name),
    t: (key) => key,
    toast: (...notice) => notices.push(notice),
    errorText: (error) => error.message || String(error),
    errorPayload: (error) => error,
    setTruncatableText: (element, value) => {
      element.textContent = value;
    },
  });
  return { state, document, query, notices, events, calls: native.calls, ...controller };
}

test("validation claims once, saves project inputs and refreshes before starting the sidecar", async (t) => {
  const fixture = setup(t, {
    invoke: async (command, args, state) => {
      if (args.method === "project.refresh") return state.project;
      return { ok: true, diagnostics: [{ severity: "warning", message: "Check title" }] };
    },
  });
  const other = createDocument({ path: "/other/draft.md", content: "" });
  updateDocumentContent(other, "Unrelated unsaved work");
  fixture.state.documents.push(other);
  updateDocumentContent(fixture.document, "# Latest chapter");
  const first = fixture.validateActiveBook();
  assert.equal(fixture.state.bookPreparing, true);
  assert.equal(fixture.query("#book-validate").disabled, true);
  await fixture.validateActiveBook();
  await first;
  assert.deepEqual(fixture.events, [
    "confirm",
    "save",
    "project.refresh",
    "book.validate",
    "renderProblems",
    "sidebar:problems",
  ]);
  assert.equal(fixture.document.savedContent, "# Latest chapter");
  assert.equal(other.savedContent, "");
  assert.deepEqual(fixture.notices, [
    ["bookOperationAlreadyRunning", "warning"],
    ["bookValidWithWarnings", "warning"],
  ]);
  assert.equal(fixture.query("#book-validate").disabled, false);
  assert.equal(fixture.query("#book-chapter-up").disabled, true);
  assert.equal(fixture.state.activeBookCompletion, null);
  assert.equal(fixture.state.bookPreparing, false);
});

for (const reason of ["confirmation", "save"]) {
  test("aborted " + reason + " never starts a book task", async (t) => {
    const fixture = setup(t, {
      confirm: async () => reason !== "confirmation",
      save: async () => false,
    });
    updateDocumentContent(fixture.document, "Keep my draft");
    await fixture.validateActiveBook();
    assert.equal(fixture.calls.length, 0);
    assert.equal(fixture.document.content, "Keep my draft");
    assert.equal(fixture.document.savedContent, "# Saved");
    assert.equal(fixture.state.activeBookCompletion, null);
    assert.equal(fixture.query("#book-operation-message").textContent, "");
  });
}

test("export claims before the native picker and a cancelled picker does not save or start work", async (t) => {
  const picker = deferred();
  const entered = deferred();
  const fixture = setup(t, {
    invoke: async (command) => {
      assert.equal(command, "pick_pdf_output");
      entered.resolve();
      return picker.promise;
    },
  });
  updateDocumentContent(fixture.document, "Unsaved");
  const first = fixture.exportActiveBook();
  await entered.promise;
  await fixture.exportActiveBook();
  assert.equal(fixture.calls.length, 1);
  assert.equal(fixture.calls[0].args.suggested_path, "/book/dist/book.pdf");
  picker.resolve(null);
  await first;
  assert.equal(fixture.document.savedContent, "# Saved");
  assert.equal(fixture.state.activeBookCompletion, null);
  assert.equal(fixture.state.bookPreparing, false);
});

test("project transition cancels the old task and waits for settlement before allowing another", async (t) => {
  const pending = deferred();
  const entered = deferred();
  let validations = 0;
  const fixture = setup(t, {
    invoke: async (command, args, state) => {
      if (command === "sidecar_cancel") return { cancel_requested: true };
      if (args.method === "project.refresh") return state.project;
      if (++validations === 1) {
        entered.resolve();
        return pending.promise;
      }
      return { ok: true, diagnostics: [] };
    },
  });
  const first = fixture.validateActiveBook();
  await entered.promise;
  const requestId = fixture.state.activeBookRequestId;
  const handoff = fixture.invalidateBookTaskForProjectChange();
  fixture.state.project = { path: "/next-book", book: {} };
  fixture.state.projectGeneration += 1;
  await fixture.exportActiveBook();
  assert.equal(fixture.calls.filter((call) => call.command === "pick_pdf_output").length, 0);
  assert.deepEqual(fixture.calls.at(-1), {
    command: "sidecar_cancel",
    args: { request_id: requestId },
  });
  pending.resolve({ ok: false, diagnostics: [{ severity: "error", message: "Stale" }] });
  await first;
  await handoff;
  assert.deepEqual(fixture.state.projectDiagnostics, []);
  assert.equal(fixture.query("#book-operation-message").textContent, "");
  assert.equal(fixture.state.bookCancellationHandoff, null);
  await fixture.validateActiveBook();
  assert.equal(validations, 2);
  assert.deepEqual(fixture.notices.at(-1), ["bookValid", "success"]);
});

test("changing projects during save prevents refresh and validation of the old project", async (t) => {
  const pending = deferred();
  const entered = deferred();
  const fixture = setup(t, {
    save: async () => {
      entered.resolve();
      return pending.promise;
    },
  });
  updateDocumentContent(fixture.document, "Unsaved");
  const operation = fixture.validateActiveBook();
  await entered.promise;
  const handoff = fixture.invalidateBookTaskForProjectChange();
  fixture.state.project = { path: "/next-book", book: {} };
  pending.resolve(true);
  await operation;
  await handoff;
  assert.equal(fixture.calls.length, 0);
  assert.equal(fixture.state.activeBookCompletion, null);
});

test("export keeps create-only output and exposes the engine's actual output path", async (t) => {
  const fixture = setup(t, {
    invoke: async (command, args, state) => {
      if (command === "pick_pdf_output") return "/exports/requested.pdf";
      if (command === "open_path" || command === "reveal_path") return;
      if (args.method === "project.refresh") return state.project;
      return { output_path: "/exports/actual.pdf", pages: 2 };
    },
  });
  await fixture.exportActiveBook();
  const exported = fixture.calls.find((call) => call.args?.method === "book.export");
  assert.deepEqual(exported.args.params, {
    project_path: "/book",
    output_path: "/exports/requested.pdf",
    create_only: true,
  });
  assert.equal(fixture.state.bookOutputPath, "/exports/actual.pdf");
  assert.equal(fixture.query("#book-output-result-name").textContent, "actual.pdf");
  await fixture.openBookOutput();
  await fixture.openBookOutput(true);
  assert.deepEqual(fixture.calls.slice(-2), [
    { command: "open_path", args: { path: "/exports/actual.pdf" } },
    { command: "reveal_path", args: { path: "/exports/actual.pdf" } },
  ]);
});

test("task errors retain diagnostic details and release the guard; cancellation stays quiet", async (t) => {
  let error = {
    message: "Invalid book",
    details: { diagnostics: [{ severity: "error", message: "Missing chapter" }] },
  };
  const fixture = setup(t, {
    invoke: async (command, args, state) => {
      if (args.method === "project.refresh") return state.project;
      throw error;
    },
  });
  await fixture.validateActiveBook();
  assert.deepEqual(fixture.state.projectDiagnostics, error.details.diagnostics);
  assert.deepEqual(fixture.notices, [["Invalid book", "error"]]);
  assert.equal(fixture.state.activeBookCompletion, null);
  error = { data: { application_code: "MARDAS-JOB-CANCELLED" } };
  await fixture.validateActiveBook();
  assert.equal(fixture.notices.length, 1);
  assert.equal(fixture.query("#book-operation-message").textContent, "searchCancelled");
  assert.equal(fixture.query("#book-validate").disabled, false);
});
