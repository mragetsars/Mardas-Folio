/**
 * The same Persian word, typed on the keyboards people actually have.
 *
 * ی/ي, ک/ك and the zero-width non-joiner are invisible distinctions on screen.
 * Every filter the interface offers has to read them as one word, or it answers
 * "no such setting" about something the user is looking at.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { filterCommands } from "../frontend/js/core/command-palette.mjs";
import { foldForFilter, foldPersianLetters } from "../frontend/js/core/persian.mjs";
import { foldPersianLetters as reExported } from "../frontend/js/core/find-replace.mjs";

const ZWNJ = "‌";

test("letter folding maps the Arabic forms onto the Persian ones", () => {
  assert.equal(foldPersianLetters("كتاب"), "کتاب");
  assert.equal(foldPersianLetters("تنظيمات"), "تنظیمات");
  assert.equal(foldPersianLetters("علی"), "علی");
});

test("letter folding is one character for one, so offsets survive", () => {
  for (const value of ["كتاب", "تنظيمات", "یک ك و یك ي", "plain latin"]) {
    assert.equal(foldPersianLetters(value).length, value.length, value);
  }
});

test("letters that only look alike are left alone", () => {
  // آ and ا are different letters; digits from different scripts mean
  // different things. Folding them would merge words that are not the same.
  assert.equal(foldPersianLetters("آب"), "آب");
  assert.equal(foldPersianLetters("۱۲۳"), "۱۲۳");
  assert.equal(foldPersianLetters("123"), "123");
});

test("document search keeps importing the fold from find-replace", () => {
  assert.equal(reExported, foldPersianLetters);
});

test("filter folding also drops zero-width joiners and case", () => {
  assert.equal(foldForFilter(`پیش${ZWNJ}نمایش`), "پیشنمایش");
  assert.equal(foldForFilter("پیش نمایش"), "پیش نمایش");
  assert.equal(foldForFilter("Settings"), "settings");
  assert.equal(foldForFilter(`  تنظيمات${ZWNJ}  `), "تنظیمات");
});

const COMMANDS = [
  { id: "settings", label: "تنظیمات", keywords: "preferences appearance", priority: 40 },
  { id: "book", label: "پروژه کتاب جدید", keywords: "book project", priority: 30 },
  { id: "preview", label: `پیش${ZWNJ}نمایش`, keywords: "preview", priority: 20 },
  { id: "export", label: "Export PDF", keywords: "خروجی", priority: 10 },
];

test("the command palette finds a command typed with an Arabic yeh", () => {
  const persian = filterCommands(COMMANDS, "تنظیمات").map((c) => c.id);
  const arabic = filterCommands(COMMANDS, "تنظيمات").map((c) => c.id);
  assert.deepEqual(persian, ["settings"]);
  assert.deepEqual(arabic, persian);
});

test("the command palette finds a command typed with an Arabic kaf", () => {
  const persian = filterCommands(COMMANDS, "کتاب").map((c) => c.id);
  const arabic = filterCommands(COMMANDS, "كتاب").map((c) => c.id);
  assert.deepEqual(persian, ["book"]);
  assert.deepEqual(arabic, persian);
});

test("the command palette finds a joined word however the joiner was typed", () => {
  const withJoiner = filterCommands(COMMANDS, `پیش${ZWNJ}نمایش`).map((c) => c.id);
  const withNothing = filterCommands(COMMANDS, "پیشنمایش").map((c) => c.id);
  assert.deepEqual(withJoiner, ["preview"]);
  assert.deepEqual(withNothing, withJoiner);
});

test("folding does not widen a search into unrelated commands", () => {
  assert.deepEqual(filterCommands(COMMANDS, "zzzz"), []);
  assert.deepEqual(filterCommands(COMMANDS, "آب"), []);
  // A Latin query still matches only what contains it.
  assert.deepEqual(filterCommands(COMMANDS, "export").map((c) => c.id), ["export"]);
});

test("an empty query still returns commands by priority", () => {
  assert.deepEqual(filterCommands(COMMANDS, "").map((c) => c.id),
                   ["settings", "book", "preview", "export"]);
});
