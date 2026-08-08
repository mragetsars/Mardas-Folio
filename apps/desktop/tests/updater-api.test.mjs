import test from "node:test";
import assert from "node:assert/strict";
import { updaterStatus, checkForUpdates, installUpdate } from "../frontend/js/core/updater-api.mjs";

test("updater API uses native commands without direct network access", async () => {
  const calls = [];
  globalThis.__TAURI__ = {
    core: {
      invoke: async (command, args) => {
        calls.push({ command, args });
        return { ok: true, command };
      },
    },
    event: { listen: async () => () => {} },
  };

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

  delete globalThis.__TAURI__;
});

test("updater API rejects missing expected version before invoking native code", async () => {
  let invoked = false;
  globalThis.__TAURI__ = {
    core: {
      invoke: async () => {
        invoked = true;
        return {};
      },
    },
    event: { listen: async () => () => {} },
  };

  await assert.rejects(() => installUpdate("   "), /version/i);
  assert.equal(invoked, false);
  delete globalThis.__TAURI__;
});
