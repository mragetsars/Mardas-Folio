import test from "node:test";
import * as json from "../../frontend/js/features/documents/json-source.mjs";
import * as shelf from "../../frontend/js/features/library/draft-order.mjs";
import { enableDialogBackdrop } from "../../frontend/js/ui/dialog-backdrop.mjs";

function pureSuite({
  jsonTree,
  replaceScalar,
  updateResumeFields,
  orderedShelf,
  captureDrafts,
  promoteDraft,
}) {
  const checks = [];
  function eq(actual, expected, label) {
    if (JSON.stringify(actual) !== JSON.stringify(expected))
      throw Error(label + " — " + JSON.stringify(actual));
    checks.push(label);
  }
  function rejects(fn, label) {
    let hit = false;
    try {
      fn();
    } catch {
      hit = true;
    }
    eq(hit, true, label);
  }
  const input =
    '{\r\n  "basics":{"name":"Mina","name":"مینا"}, "id":900719925474099312345, "price":1.00e+02, "notes":[null,true,"a\\\\b"], "__proto__": false\r\n}\n';
  const root = jsonTree(input);
  eq(
    root.children.map((v) => v.key),
    ["basics", "id", "price", "notes", "__proto__"],
    "JSON member order and literal __proto__",
  );
  eq(
    input.slice(root.children[1].node.from, root.children[1].node.to),
    "900719925474099312345",
    "Arbitrary-precision integer token",
  );
  eq(
    updateResumeFields(input, { name: "سارا" }),
    input.replace('"مینا"', '"سارا"'),
    "Duplicate names and exact bytes outside edit",
  );
  eq(updateResumeFields(input, { name: "مینا" }), input, "No-op preserves CRLF and final newline");
  const added = updateResumeFields(input, { email: "new@example.test" });
  eq(
    added,
    input.replace('"مینا"}', '"مینا", "email": "new@example.test"}'),
    "Add optional résumé property without reprinting",
  );
  const price = root.children[2].node;
  eq(
    replaceScalar(input, price, "2.30E-5"),
    input.replace("1.00e+02", "2.30E-5"),
    "Editable exponent token",
  );
  rejects(() => replaceScalar(input, price, '"no"'), "Refuse number-to-string accident");
  rejects(() => replaceScalar(input, price, "01"), "Refuse invalid leading zero");
  rejects(() => replaceScalar(input, price, "[]"), "Refuse unrequested container");
  rejects(() => jsonTree('{"x":}'), "Malformed JSON stays editable in Source");
  rejects(
    () => jsonTree("[".repeat(125) + "0" + "]".repeat(125)),
    "Guard deeply nested field view",
  );
  eq(jsonTree("false").type, "boolean", "Root boolean");
  eq(jsonTree("null").type, "null", "Root null");
  eq(jsonTree("[]").children.length, 0, "Empty array");
  eq(jsonTree('{"x":"a\\nb\\t\\"\\\\z"}').children.length, 1, "Escaped string tokens");
  const row = (id) => ({ id }),
    ids = (list) => list.map((r) => r.id);
  const saved = ["a", "b", "c"].map(row),
    drafts = ["x", "y", "z"].map(row);
  const merged = ["a", "y", "x", "b", "z", "c"].map(row);
  const pins = captureDrafts(merged, new Set(ids(saved)));
  eq(
    ids(orderedShelf(saved, drafts, pins)),
    ids(merged),
    "Restore mixed shelf order after restart",
  );
  const promoted = promoteDraft(saved, row("x"), pins);
  eq(ids(promoted.rows), ["a", "x", "b", "c"], "Saving a draft persists its actual position");
  eq(
    ids(orderedShelf(promoted.rows, ["y", "z"].map(row), promoted.pins)),
    ids(merged),
    "Promotion preserves neighbouring drafts",
  );
  const promotedTwice = promoteDraft(promoted.rows, row("y"), promoted.pins);
  eq(
    ids(orderedShelf(promotedTwice.rows, [row("z")], promotedTwice.pins)),
    ids(merged),
    "Multiple promotions in opposite order",
  );
  eq(
    ids(orderedShelf([row("a"), row("c")], drafts, pins)),
    ["a", "y", "x", "z", "c"],
    "Missing anchor uses surviving neighbour",
  );
  eq(
    ids(orderedShelf(saved, drafts, [])),
    ["a", "b", "c", "x", "y", "z"],
    "Fresh drafts follow files",
  );
  eq(
    ids(orderedShelf(saved, [row("new")], pins)),
    ["a", "b", "c", "new"],
    "Outdated draft pins ignored",
  );
  const first = promoteDraft([], row("x"), captureDrafts([row("y"), row("x")], new Set()));
  eq(
    ids(orderedShelf(first.rows, [row("y")], first.pins)),
    ["y", "x"],
    "First save on an entirely draft shelf",
  );
  return checks;
}
function popupSuite(enableDialogBackdrop) {
  const results = [];
  function run(label, sequence, allowed, expected) {
    const handlers = new Map();
    const dialog = {
      closes: 0,
      addEventListener(k, fn) {
        handlers.set(k, fn);
      },
      getBoundingClientRect() {
        return { left: 30, top: 30, right: 110, bottom: 110 };
      },
      close() {
        this.closes++;
      },
    };
    enableDialogBackdrop(dialog, () => allowed);
    for (const [type, x, y, pointer = 1, button = 0, child = false] of sequence)
      handlers.get(type)?.({
        target: child ? {} : dialog,
        button,
        pointerId: pointer,
        clientX: x,
        clientY: y,
        preventDefault() {},
      });
    if (dialog.closes !== expected) throw Error(label);
    results.push(label);
  }
  run(
    "Backdrop gesture closes exactly once",
    [
      ["pointerdown", 4, 4],
      ["pointerup", 4, 4],
      ["click", 4, 4],
    ],
    true,
    1,
  );
  run(
    "Selection dragged out stays open",
    [
      ["pointerdown", 40, 40, 1, 0, true],
      ["pointerup", 4, 4],
      ["click", 4, 4],
    ],
    true,
    0,
  );
  run(
    "Inside dialog padding stays open",
    [
      ["pointerdown", 35, 36],
      ["pointerup", 35, 36],
      ["click", 35, 36],
    ],
    true,
    0,
  );
  run(
    "Different pointers do not dismiss",
    [
      ["pointerdown", 4, 4, 1],
      ["pointerup", 4, 4, 2],
      ["click", 4, 4],
    ],
    true,
    0,
  );
  run(
    "Escape-disabled save in progress stays open",
    [
      ["pointerdown", 4, 4],
      ["pointerup", 4, 4],
      ["click", 4, 4],
    ],
    false,
    0,
  );
  run(
    "Pointer cancellation cancels dismissal",
    [
      ["pointerdown", 4, 4],
      ["pointercancel", 4, 4],
      ["pointerup", 4, 4],
      ["click", 4, 4],
    ],
    true,
    0,
  );
  run(
    "Right click does not dismiss",
    [
      ["pointerdown", 4, 4, 1, 2],
      ["pointerup", 4, 4, 1, 2],
      ["click", 4, 4],
    ],
    true,
    0,
  );
  return results;
}
test("lossless JSON and draft-file shelf transitions", () => pureSuite({ ...json, ...shelf }));
test("dialog backdrop gestures and cancellation", () => popupSuite(enableDialogBackdrop));
