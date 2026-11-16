/** Install an observable native boundary and restore it even if an assertion fails. */
export function installTauriFixture(t, { invoke = async () => ({ ok: true }) } = {}) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "__TAURI__");
  const calls = [];
  Object.defineProperty(globalThis, "__TAURI__", {
    configurable: true,
    writable: true,
    value: {
      core: {
        invoke: async (command, args) => {
          calls.push({ command, args });
          return invoke(command, args);
        },
      },
      event: { listen: async () => () => {} },
    },
  });
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, "__TAURI__", previous);
    else delete globalThis.__TAURI__;
  });
  return { calls };
}
