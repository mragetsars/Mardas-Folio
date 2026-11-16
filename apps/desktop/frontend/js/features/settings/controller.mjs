import { createSettingsPanel } from "./settings-panel.mjs";
import { DEFAULT_PREFERENCES, writePreferences } from "./preferences.mjs";
/** Owns this feature's DOM interactions; cross-feature actions are injected. */
export function createSettingsController({ state, query: $, getModalManager, applyInterfacePreferences, setLocale, t, toast }) {
  const settingsPanel = createSettingsPanel($("#settings-form"));
  function fillSettingsForm() {
    $("#setting-theme").value = state.preferences.theme;
    $("#setting-accent").value = state.preferences.accent;
    const zoomSetting = $("#setting-document-zoom");
    if (zoomSetting) zoomSetting.value = String(state.preferences.documentZoom);
    $("#setting-motion").value = state.preferences.reducedMotion;
    $("#setting-auto-preview").checked = state.preferences.autoPreview;
    $("#setting-typewriter").checked = state.preferences.typewriter;
    if ($("#setting-writing-width")) $("#setting-writing-width").value = state.preferences.writingWidth;
    $("#setting-locale").value = state.locale;
    settingsPanel.updateAccentPreview();
  }

  function openSettings(section = "settings-appearance") {
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
      ...state.preferences,
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
    state.preferences = writePreferences({
      ...DEFAULT_PREFERENCES,
      onboardingComplete: state.preferences.onboardingComplete,
    });
    applyInterfacePreferences();
    fillSettingsForm();
    settingsPanel.showSection();
    toast(t("settingsReset"), "success");
  }
  return { openSettings, closeSettings, submitSettings, resetSettings };
}
