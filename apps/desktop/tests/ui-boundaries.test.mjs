import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";

test("UI components receive native actions without depending on the application entrypoint", () => {
  const directory = new URL("../frontend/js/ui/", import.meta.url);
  for (const name of readdirSync(directory).filter((name) => name.endsWith(".mjs"))) {
    const source = readFileSync(new URL(name, directory), "utf8");
    assert.doesNotMatch(source, /(?:from\s*|import\s*\()\s*["'][^"']*\/(?:main|tauri)\.mjs["']/, name);
    assert.doesNotMatch(source, /\b__TAURI__\b/, name);
  }
});
