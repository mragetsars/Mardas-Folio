import test from "node:test";
import assert from "node:assert/strict";
import { filterCommands } from "../frontend/js/core/command-palette.mjs";

const commands = [
  { id: "open", label: "Open document", keywords: "file markdown", priority: 20 },
  { id: "project", label: "Open project", keywords: "folder workspace", priority: 10 },
  { id: "save", label: "Save", keywords: "write", priority: 30 },
  { id: "disabled", label: "Secret", enabled: false },
];

test("command palette ranks labels and filters disabled commands", () => {
  assert.deepEqual(filterCommands(commands, "open").map((item) => item.id), ["open", "project"]);
  assert.deepEqual(filterCommands(commands, "folder").map((item) => item.id), ["project"]);
  assert.equal(filterCommands(commands, "").some((item) => item.id === "disabled"), false);
});
