import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const index = readFileSync(new URL("../../frontend/index.html", import.meta.url), "utf8");
const projectWorkspace = readFileSync(
  new URL("../../frontend/js/features/workspace/project.mjs", import.meta.url),
  "utf8",
);
const main = readFileSync(new URL("../../frontend/js/main.mjs", import.meta.url), "utf8");

test("an open project exposes one close action with an explicit keep-open-tabs contract", () => {
  assert.match(index, /id="close-project"[^>]*data-i18n-title="closeProjectHelp"/);
  assert.match(index, /id="close-project"[\s\S]*?<span data-i18n="closeProject">/);
  assert.match(main, /\{\s*id: "close-project"[\s\S]*enabled: Boolean\(state\.project\?\.path\)/);
  assert.match(main, /\$\("#close-project"\)\.addEventListener\("click", closeActiveProject\)/);
  assert.match(
    main,
    /function closeActiveProject\(\)[\s\S]*const cleanup = clearProjectState\(\)[\s\S]*return cleanup/,
  );
});

test("book projects expose one project-level close action in the Project inspector", () => {
  assert.match(
    index,
    /id="sidebar-panel-project"[\s\S]*?id="close-project"[^>]*data-i18n-title="closeProjectHelp"/,
  );
  const projectFileSection =
    index.match(
      /<section class="navigator-section navigator-project-section[\s\S]*?<\/section>/,
    )?.[0] || "";
  assert.notEqual(projectFileSection, "");
  assert.doesNotMatch(projectFileSection, /id="close-project"/);
  assert.doesNotMatch(index, /id="book-close-project"/);
  assert.match(projectWorkspace, /\$\("#close-project"\)\.hidden = !project/);
  assert.doesNotMatch(main, /book-close-project/);
});

test("closing the project clears project state without closing open tabs", () => {
  const start = main.indexOf("function clearProjectState() {");
  const end = main.indexOf("function closeActiveProject()", start);
  const clear = main.slice(start, end);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  assert.match(clear, /resetProjectSession\(state\)/);
  assert.match(clear, /persistSession\(\)/);
  assert.doesNotMatch(clear, /closeDocument\(/);
  assert.match(
    main,
    /function closeActiveProject\(\)[\s\S]*const cleanup = clearProjectState\(\)[\s\S]*showView\("workspace"\)/,
  );
});
