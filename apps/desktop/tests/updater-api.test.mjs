import { installTauriFixture } from "./fixtures/tauri.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { updaterStatus, checkForUpdates, installUpdate } from "../frontend/js/core/updater-api.mjs";

test("updater API uses native commands without direct network access", async (t) => {
  const { calls } = installTauriFixture(t);


  await updaterStatus();
  await checkForUpdates();
  await installUpdate("1.30.0");

  assert.deepEqual(
    calls.map((item) => item.command),
    ["updater_status", "updater_check", "updater_install"],
  );
  assert.deepEqual(calls[0].args, {});
  assert.deepEqual(calls[1].args, {});
  assert.deepEqual(calls[2].args, { expectedVersion: "1.30.0" });

});

test("updater API rejects missing expected version before invoking native code", async (t) => {
  const { calls } = installTauriFixture(t);

  await assert.rejects(() => installUpdate("   "), /version/i);
  assert.equal(calls.length, 0);
});
