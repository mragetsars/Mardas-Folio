import { updaterStatus, checkForUpdates, installUpdate } from "../../adapters/updater-api.mjs";
import { saveDocumentsBeforeUpdate } from "../../core/update-preparation.mjs";
/** Owns this feature's DOM interactions; cross-feature actions are injected. */
export function createUpdater({ state, query: $, t, toast, errorText, isDirty, confirm, save, refreshAuthoring }) {
  function updateUi() {
    const status = state.updateStatus;
    const check = state.updateCheck;
    const configured = Boolean(status?.configured);
    const current = status?.current_version || $("#app-version")?.textContent || "";
    $("#update-current-version").textContent = current;
    $("#update-channel").textContent = status?.channel || "stable";
    $("#check-updates").disabled = !configured || state.updateInstalling;
    $("#install-update").disabled = state.updateInstalling || !check?.available;
    $("#install-update").classList.toggle("hidden", !check?.available);
    $("#update-progress").classList.toggle("hidden", !state.updateInstalling);
    if (!configured) {
      $("#update-state").dataset.state = "disabled";
      $("#update-state").textContent = t("updatesUnavailable");
      $("#update-detail").textContent = t("updatesUnavailableHelp");
      return;
    }
    if (state.updateInstalling) {
      $("#update-state").dataset.state = "working";
      $("#update-state").textContent = t(state.updatePreparing ? "updateSavingDocuments" : "updateInstalling");
      const total = Number(state.updateTotal) || 0;
      const downloaded = Number(state.updateDownloaded) || 0;
      const percent = total > 0 ? Math.min(100, Math.round((downloaded / total) * 100)) : 0;
      $("#update-progress-bar").value = percent;
      $("#update-progress-label").textContent = total > 0 ? `${percent}%` : "…";
      $("#update-detail").textContent = check?.version ? `${t("updateVersion")} ${check.version}` : "";
      return;
    }
    if (check?.available) {
      $("#update-state").dataset.state = "available";
      $("#update-state").textContent = t("updateAvailable");
      $("#update-detail").textContent = `${t("updateVersion")} ${check.version}${check.pub_date ? ` · ${check.pub_date}` : ""}`;
      $("#update-notes").textContent = check.notes || t("noReleaseNotes");
      $("#update-notes").classList.remove("hidden");
      return;
    }
    $("#update-notes").classList.add("hidden");
    if (check && !check.available) {
      $("#update-state").dataset.state = "ready";
      $("#update-state").textContent = t("upToDate");
      $("#update-detail").textContent = `${t("currentVersion")} ${current}`;
    } else {
      $("#update-state").dataset.state = "ready";
      $("#update-state").textContent = t("updatesReady");
      $("#update-detail").textContent = t("updatesManualHelp");
    }
  }

  async function initializeUpdater() {
    try {
      state.updateStatus = await updaterStatus();
    } catch {
      state.updateStatus = {
        configured: false,
        current_version: $("#app-version")?.textContent || "",
        channel: "stable",
        reason: "unavailable",
      };
    }
    updateUi();
  }

  async function checkUpdates() {
    if (!state.updateStatus?.configured || state.updateInstalling) {
      updateUi();
      return;
    }
    const button = $("#check-updates");
    button.disabled = true;
    $("#update-state").dataset.state = "working";
    $("#update-state").textContent = t("checkingUpdates");
    $("#update-detail").textContent = t("checkingUpdatesHelp");
    $("#update-notes").classList.add("hidden");
    try {
      state.updateCheck = await checkForUpdates();
      updateUi();
      if (!state.updateCheck?.available) toast(t("upToDate"), "success");
    } catch (error) {
      state.updateCheck = null;
      $("#update-state").dataset.state = "error";
      $("#update-state").textContent = t("updateCheckFailed");
      $("#update-detail").textContent = errorText(error);
      button.disabled = false;
    }
  }

  async function installAvailableUpdate() {
    if (!state.updateCheck?.available || state.updateInstalling) return;
    if (state.activeRequestId || state.activeBookRequestId || state.activeProjectSearchRequestId) {
      toast(t("updateFinishTasks"), "info");
      return;
    }
    state.updateInstalling = true;
    state.updatePreparing = true;
    state.updateDownloaded = 0;
    state.updateTotal = 0;
    refreshAuthoring();
    updateUi();
    try {
      const ready = await saveDocumentsBeforeUpdate({
        getDocuments: () => state.documents,
        isDirty,
        confirm: () => confirm({
          title: t("updateSaveDocuments"),
          message: t("updateSaveDocumentsHelp"),
          confirmLabel: t("saveAndInstallUpdate"),
        }),
        save,
      });
      if (!ready) {
        toast(t("updatePostponed"), "info");
        return;
      }
      state.updatePreparing = false;
      updateUi();
      await installUpdate(state.updateCheck.version);
      toast(t("updateInstalled"), "success");
    } catch (error) {
      $("#update-state").dataset.state = "error";
      $("#update-state").textContent = t("updateInstallFailed");
      $("#update-detail").textContent = errorText(error);
      $("#check-updates").disabled = false;
      $("#install-update").disabled = false;
    } finally {
      state.updateInstalling = false;
      state.updatePreparing = false;
      refreshAuthoring();
      if ($("#update-state").dataset.state !== "error") updateUi();
      $("#update-progress").classList.add("hidden");
    }
  }
  return { updateUi, initializeUpdater, checkUpdates, installAvailableUpdate };
}
