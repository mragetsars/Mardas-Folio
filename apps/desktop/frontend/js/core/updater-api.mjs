import { invoke } from "./tauri.mjs";

export async function updaterStatus() {
  return invoke("updater_status");
}

export async function checkForUpdates() {
  return invoke("updater_check");
}

export async function installUpdate(expectedVersion) {
  const value = String(expectedVersion || "").trim();
  if (!value || value.length > 128) throw new Error("Invalid update version.");
  return invoke("updater_install", { expectedVersion: value });
}
