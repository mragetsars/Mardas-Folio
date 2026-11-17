import test from "node:test";
import assert from "node:assert/strict";
import { createProjectWorkspace } from "../../frontend/js/features/workspace/project.mjs";
import { installTauriFixture } from "../fixtures/tauri.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function setup(t, { invoke, activeDocument = () => null } = {}) {
  const state = {
    project: null,
    projectRequestSequence: 0,
    documentActivationSequence: 0,
    bibliographyEntries: [],
    activeProjectSearchRequestId: null,
    projectSearchSequence: 0,
  };
  const events = [];
  const notices = [];
  const native = installTauriFixture(t, { invoke });
  const controller = createProjectWorkspace({
    state,
    activeDocument,
    invalidateBookTaskForProjectChange: () => {
      events.push("cancelBook");
      return Promise.resolve(true);
    },
    applyProjectPayload: (payload) => {
      state.project = payload.project || payload;
      events.push(state.project.path);
    },
    showView: (name) => events.push("view:" + name),
    activateSidebar: (name) => events.push("sidebar:" + name),
    openProjectRelativeFile: async (path) => events.push("file:" + path),
    t: (key) => key,
    toast: (...notice) => notices.push(notice),
    errorText: (error) => error.message,
  });
  return { state, events, notices, calls: native.calls, ...controller };
}

test("overlapping project loads apply only the most recent reply", async (t) => {
  const pending = deferred();
  const entered = deferred();
  const fixture = setup(t, {
    invoke: async (command, args) => {
      if (args.params.path === "/first") {
        entered.resolve();
        return pending.promise;
      }
      return { project: { path: "/second" }, book: { chapters: [{ path: "two.md" }] } };
    },
  });
  const first = fixture.loadProject("/first");
  await entered.promise;
  const second = fixture.loadProject("/second");
  pending.resolve({ project: { path: "/first" }, book: { chapters: [{ path: "one.md" }] } });
  assert.equal(await first, null);
  await second;
  assert.equal(fixture.state.project.path, "/second");
  assert.deepEqual(fixture.events, [
    "cancelBook",
    "cancelBook",
    "/second",
    "view:workspace",
    "sidebar:project",
    "file:two.md",
  ]);
  assert.deepEqual(fixture.notices, [["projectOpened", "success"]]);
});

test("a user activation during project loading keeps focus while attaching the project", async (t) => {
  const pending = deferred();
  const entered = deferred();
  const fixture = setup(t, {
    invoke: async () => {
      entered.resolve();
      return pending.promise;
    },
  });
  const loading = fixture.loadProject("/book");
  await entered.promise;
  fixture.state.documentActivationSequence += 1;
  pending.resolve({ path: "/book", book: { chapters: [{ path: "one.md" }] } });
  await loading;
  assert.equal(fixture.state.project.path, "/book");
  assert.deepEqual(fixture.events, ["cancelBook", "/book"]);
  assert.deepEqual(fixture.notices, []);
});

test("restoring a session suppresses announcements and automatic chapter activation", async (t) => {
  const fixture = setup(t, {
    invoke: async () => ({
      path: "/book",
      book: { chapters: [{ path: "one.md" }] },
    }),
  });
  await fixture.loadProject("/book", { announce: false, openFirstChapter: false });
  assert.deepEqual(fixture.events, ["cancelBook", "/book", "view:workspace", "sidebar:project"]);
  assert.deepEqual(fixture.notices, []);
});

test("refresh after project closure cannot reattach the old project", async (t) => {
  const pending = deferred();
  const entered = deferred();
  const fixture = setup(t, {
    invoke: async () => {
      entered.resolve();
      return pending.promise;
    },
  });
  fixture.state.project = { path: "/book" };
  const refresh = fixture.refreshActiveProject();
  await entered.promise;
  fixture.state.project = null;
  fixture.state.projectRequestSequence += 1;
  pending.resolve({ path: "/book" });
  await refresh;
  assert.equal(fixture.state.project, null);
  assert.deepEqual(fixture.events, []);
  assert.deepEqual(fixture.notices, []);
});

test("opening the same project preserves the active document and does not cancel book work", async (t) => {
  const fixture = setup(t, {
    activeDocument: () => ({ path: "/book/two.md" }),
    invoke: async () => ({ path: "/book", book: { chapters: [{ path: "one.md" }] } }),
  });
  fixture.state.project = { path: "/book" };
  await fixture.loadProject("/book");
  assert.deepEqual(fixture.events, ["/book", "view:workspace", "sidebar:project"]);
});
