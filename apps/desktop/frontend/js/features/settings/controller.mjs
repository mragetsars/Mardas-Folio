import { createSettingsPanel } from "./settings-panel.mjs";
import { DEFAULT_PREFERENCES, writePreferences } from "./preferences.mjs";
/** Owns this feature's DOM interactions; cross-feature actions are injected. */
export function createSettingsController({
  state,
  query: $,
  getModalManager,
  applyInterfacePreferences,
  setLocale,
  t,
  toast,
}) {
  const settingsPanel = createSettingsPanel($("#settings-form"));
  let resetPending = false;
  function fillSettingsForm(preferences = state.preferences) {
    $("#setting-theme").value = preferences.theme;
    $("#setting-accent").value = preferences.accent;
    const zoomSetting = $("#setting-document-zoom");
    if (zoomSetting) zoomSetting.value = String(preferences.documentZoom);
    $("#setting-motion").value = preferences.reducedMotion;
    $("#setting-auto-preview").checked = preferences.autoPreview;
    $("#setting-typewriter").checked = preferences.typewriter;
    if ($("#setting-writing-width")) $("#setting-writing-width").value = preferences.writingWidth;
    $("#setting-locale").value = state.locale;
    settingsPanel.updateAccentPreview();
  }

  function openSettings(section = "settings-appearance") {
    resetPending = false;
    fillSettingsForm();
    settingsPanel.showSection(section);
    getModalManager().open($("#settings-modal"), { initialFocus: "#settings-search" });
  }

  function closeSettings() {
    getModalManager().close($("#settings-modal"));
  }

  function submitSettings(event) {
    event.preventDefault();
    state.preferences = writePreferences({
      ...(resetPending ? DEFAULT_PREFERENCES : state.preferences),
      onboardingComplete: state.preferences.onboardingComplete,
      theme: $("#setting-theme").value,
      accent: $("#setting-accent").value,
      documentZoom: Number($("#setting-document-zoom").value),
      writingWidth: $("#setting-writing-width")?.value || "full",
      reducedMotion: $("#setting-motion").value,
      autoPreview: $("#setting-auto-preview").checked,
      typewriter: $("#setting-typewriter").checked,
    });
    applyInterfacePreferences();
    setLocale($("#setting-locale").value);
    closeSettings();
    toast(t("settingsSaved"), "success");
  }

  function resetSettings() {
    resetPending = true;
    fillSettingsForm(DEFAULT_PREFERENCES);
    settingsPanel.showSection();
  }
  return { openSettings, closeSettings, submitSettings, resetSettings };
}
