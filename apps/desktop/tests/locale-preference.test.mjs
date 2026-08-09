import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  LOCALE_STORAGE_KEY,
  readLocalePreference,
  writeLocalePreference,
} from "../frontend/js/core/i18n.mjs";

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test("locale preference uses persisted language and a normalized fallback", () => {
  const store = storage({ [LOCALE_STORAGE_KEY]: "fa-IR" });
  assert.equal(readLocalePreference(store, "en-US"), "fa");
  assert.equal(readLocalePreference(storage(), "fa-IR"), "fa");
  assert.equal(readLocalePreference(storage(), "de-DE"), "en");
});

test("locale persistence failures never block application startup or switching", () => {
  const broken = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
  assert.equal(readLocalePreference(broken, "fa-IR"), "fa");
  assert.equal(writeLocalePreference("fa-IR", broken), "fa");
  assert.equal(writeLocalePreference("en-US", broken), "en");
});

test("native accessibility labels are routed through the interface locale", () => {
  const source = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
  assert.match(source, /id="document-tabs"[^>]*data-i18n-aria-label="openDocuments"/);
  assert.match(source, /class="book-metrics"[^>]*data-i18n-aria-label="bookStatus"/);
  assert.match(source, /id="update-progress"[^>]*data-i18n-aria-label="updateProgress"/);
});
