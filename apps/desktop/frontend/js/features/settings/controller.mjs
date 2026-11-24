import { createSettingsPanel } from "./settings-panel.mjs";
import {
  DEFAULT_PREFERENCES,
  WRITING_WIDTH_MIN,
  WRITING_WIDTH_MAX,
  writePreferences,
} from "./preferences.mjs";
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
  const form = $("#settings-form");
  const theme = form.elements.namedItem("theme");
  const accent = form.elements.namedItem("accent");
  const width = $("#setting-writing-width");
  const widthOutput = $("#setting-writing-width-value");
  width.min = WRITING_WIDTH_MIN;
  width.max = WRITING_WIDTH_MAX;
  const showWidth = () => {
    const value = width.valueAsNumber;
    widthOutput.value = value + "%";
    width.setAttribute("aria-valuetext", widthOutput.value);
    width.style.setProperty(
      "--range-progress",
      ((value - WRITING_WIDTH_MIN) / (WRITING_WIDTH_MAX - WRITING_WIDTH_MIN)) * 100 + "%",
    );
  };
  width.addEventListener("input", showWidth);
  const settingsPanel = createSettingsPanel(form);
  let resetPending = false;
  function fillSettingsForm(preferences = state.preferences) {
    theme.value = preferences.theme;
    accent.value = preferences.accent;
    const zoomSetting = $("#setting-document-zoom");
    if (zoomSetting) zoomSetting.value = String(preferences.documentZoom);
    $("#setting-motion").value = preferences.reducedMotion;
    $("#setting-auto-preview").checked = preferences.autoPreview;
    $("#setting-typewriter").checked = preferences.typewriter;
    width.value = String(preferences.writingWidth);
    showWidth();
    $("#setting-locale").value = state.locale;
  }

  function openSettings(section = "settings-appearance", initialFocus = "#settings-search") {
    resetPending = false;
    fillSettingsForm();
    settingsPanel.showSection(section);
    getModalManager().open($("#settings-modal"), { initialFocus });
  }

  function closeSettings() {
    getModalManager().close($("#settings-modal"));
  }

  function submitSettings(event) {
    event.preventDefault();
    state.preferences = writePreferences({
      ...(resetPending ? DEFAULT_PREFERENCES : state.preferences),
      onboardingComplete: state.preferences.onboardingComplete,
      theme: theme.value,
      accent: accent.value,
      documentZoom: Number($("#setting-document-zoom").value),
      writingWidth: width.valueAsNumber,
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
