import test from "node:test";
import assert from "node:assert/strict";
import { pathIdentity } from "../frontend/js/core/path-identity.mjs";

test("Windows path identity is slash and case tolerant", () => {
  assert.equal(pathIdentity("C:\\Docs\\Report.md"), pathIdentity("c:/docs/report.md"));
  assert.equal(pathIdentity("\\\\Server\\Share\\A.md"), pathIdentity("//server/share/a.md"));
});

test("POSIX path identity preserves case-sensitive filenames", () => {
  assert.notEqual(pathIdentity("/docs/A.md"), pathIdentity("/docs/a.md"));
});
