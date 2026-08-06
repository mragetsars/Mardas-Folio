import test from "node:test";
import assert from "node:assert/strict";
import {
  bibliographyIndex,
  cancelSidecarRequest,
  openProject,
  readProjectFile,
  refreshProject,
  saveProjectFile,
  startProjectSearch,
} from "../frontend/js/core/project-api.mjs";

test("project API uses bounded versioned sidecar methods", async () => {
  const calls = [];
  globalThis.__TAURI__ = {
    core: { invoke: async (command, args) => { calls.push({ command, args }); return { ok: true }; } },
    event: { listen: async () => () => {} },
  };
  await openProject("/project");
  await refreshProject("/project");
  await readProjectFile("/project", "chapter.md");
  await saveProjectFile({
    projectPath: "/project",
    relativePath: "chapter.md",
    content: "# Updated",
    expectedSha256: "abc",
  });
  const search = startProjectSearch({
    projectPath: "/project",
    query: "needle",
    regex: true,
    caseSensitive: true,
    maxResults: 25,
  });
  assert.match(search.requestId, /^project-search-/);
  await search.promise;
  await cancelSidecarRequest(search.requestId);
  await bibliographyIndex({
    projectPath: "/project",
    query: "smith",
    citedKeys: ["ref1"],
    maxResults: 50,
  });

  assert.deepEqual(calls.map((call) => call.args?.method ?? call.command), [
    "project.open",
    "project.refresh",
    "project.read",
    "project.save",
    "project.search",
    "sidecar_cancel",
    "bibliography.index",
  ]);
  assert.equal(calls[4].args.params.max_results, 25);
  assert.equal(calls[4].args.params.case_sensitive, true);
  assert.equal(calls[5].args.request_id, search.requestId);
  assert.deepEqual(calls[6].args.params.cited_keys, ["ref1"]);
  delete globalThis.__TAURI__;
});
