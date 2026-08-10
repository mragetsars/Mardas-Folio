import { basename, buildDocumentParams, defaultOutputPath, validateExportSelection } from "./core/export-request.mjs";
import { createTranslator, readLocalePreference, writeLocalePreference } from "./core/i18n.mjs";
import { onboardingIntentPresentation, onboardingPrimaryActionKey, normalizeOnboardingIntent } from "./core/onboarding.mjs";
import { PRESETS, presetById } from "./core/presets.mjs";
import {
  OPTION_FIELDS,
  OPTION_GROUPS,
  collectRenderOptions,
  fieldIsActive,
  modifiedCountsByGroup,
  modifiedKeys,
  searchOptions,
  validateOptionValue,
} from "./core/render-options.mjs";
import { addRecent, readRecents, writeRecents } from "./core/recents.mjs";
import { invoke, listen } from "./core/tauri.mjs";
import {
  createDocument,
  closeDocument,
  documentDirty,
  findDocumentByPath,
  findSavePathCollision,
  markDocumentSaved,
  pathKey,
  updateDocumentContent,
} from "./core/documents.mjs";
import {
  readRecoveries,
  recoveryForPath,
  recoveryKey,
  removeRecovery,
  saveRecovery,
} from "./core/recovery.mjs";
import { readSession, writeSession } from "./core/session.mjs";
import {
  extractCitationKeys,
  extractOutline,
  parseFrontMatter,
  textMetrics,
  upsertFrontMatter,
} from "./core/markdown-analysis.mjs";
import { prefixSelectedLines, replaceSelection, wrapSelection } from "./core/editor-commands.mjs";
import { findLiteralMatches, replaceAllLiteral } from "./core/find-replace.mjs";
import { createEditorAdapter } from "./core/editor-adapter.mjs";
import {
  captureDocumentContext,
  captureProjectContext,
  documentContextCurrent,
  projectContextCurrent,
} from "./core/request-context.mjs";
import { createSaveCoordinator } from "./core/save-coordinator.mjs";
import { beginCancellationHandoff } from "./core/task-handoff.mjs";
import { inlineDiagnosticsForDocument } from "./core/diagnostics.mjs";
import { bookTaskBlocked, claimBookTask } from "./core/book-task-state.mjs";
import {
  DEFAULT_PREFERENCES,
  applyPreferences,
  editorModeForView,
  previewVisibleForView,
  readPreferences,
  writePreferences,
} from "./core/preferences.mjs";
import { templateContent, templateList } from "./core/templates.mjs";
import {
  clampWorkspaceWidth,
  readWorkspaceLayout,
  writeWorkspaceLayout,
} from "./core/workspace-layout.mjs";
import { filterCommands } from "./core/command-palette.mjs";
import { createModalManager } from "./core/modal-manager.mjs";
import { createPageDeck } from "./preview/page-deck.mjs";
import { updaterStatus, checkForUpdates, installUpdate } from "./core/updater-api.mjs";
import {
  bibliographyIndex,
  cancelSidecarRequest,
  openProject,
  readProjectFile,
  refreshProject,
  saveProjectFile,
  startProjectSearch,
} from "./core/project-api.mjs";
import {
  addBookChapter,
  createBookProject,
  duplicateBookChapter,
  removeBookChapter,
  reorderBookChapters,
  startBookExport,
  startBookPreview,
  startBookValidation,
} from "./core/book-api.mjs";
import {
  importDocumentAsset,
  listDocumentAssets,
  previewDocumentPage,
  previewDocumentText,
  readDocument,
  readTextDocument,
  saveDocument,
  saveTextDocument,
  validateDocumentText,
} from "./core/authoring-api.mjs";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {
  locale: readLocalePreference(undefined, navigator.language),
  presetId: "general",
  sourcePath: "",
  outputPath: "",
  activeRequestId: null,
  outputResult: null,
  bookOutputPath: null,
  recents: readRecents(),
  documents: [],
  activeDocumentId: null,
  previewTimer: null,
  recoveryTimers: new Map(),
  previewSequence: 0,
  validationSequence: 0,
  assetSequence: 0,
  pendingRecovery: null,
  recoveryQueue: [],
  findMatches: [],
  findIndex: -1,
  activeSidebar: "outline",
  project: null,
  projectGeneration: 0,
  projectRequestSequence: 0,
  projectFileRequests: new Map(),
  documentOpenRequests: new Map(),
  projectSearchSequence: 0,
  activeProjectSearchRequestId: null,
  bibliographySequence: 0,
  bibliographyEntries: [],
  projectDiagnostics: [],
  activeBookRequestId: null,
  activeBookCompletion: null,
  bookCancellationHandoff: null,
  bookRequestSequence: 0,
  chapterModalMode: null,
  chapterModalPath: null,
  previewSyncing: false,
  preferences: readPreferences(),
  workspaceLayout: readWorkspaceLayout(),
  onboardingStep: 0,
  onboardingIntent: null,
  commandIndex: 0,
  visibleCommands: [],
  updateStatus: null,
  updateCheck: null,
  updateInstalling: false,
  updateDownloaded: 0,
  updateTotal: 0,
};
let editorAdapter = null;
let modalManager = null;
const saveCoordinator = createSaveCoordinator({ isDirty: documentDirty });
const translator = createTranslator(state.locale);
const t = (key) => translator.t(key);

function currentEditor() {
  return editorAdapter || $("#markdown-editor");
}

function requestId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function activeDocument() {
  return state.documents.find((document) => document.id === state.activeDocumentId) ?? null;
}

function activeProjectPath() {
  return state.project?.path ?? null;
}

function requestContext(model = activeDocument()) {
  return captureDocumentContext(model, activeProjectPath());
}

function contextIsCurrent(context, options = {}) {
  return documentContextCurrent(context, {
    documents: state.documents,
    activeDocumentId: state.activeDocumentId,
    projectPath: activeProjectPath(),
  }, options);
}

function currentProjectContext() {
  return captureProjectContext(activeProjectPath(), state.projectGeneration);
}

function projectContextIsCurrent(context) {
  return projectContextCurrent(context, {
    projectPath: activeProjectPath(),
    projectGeneration: state.projectGeneration,
  });
}

function isMarkdownModel(model) {
  return !model || ["markdown", "md"].includes(String(model.kind || "markdown").toLowerCase());
}

function isMarkdownPath(path) {
  return /\.(?:md|markdown)$/i.test(String(path || ""));
}

function setLocale(value) {
  state.locale = writeLocalePreference(value);
  translator.locale = state.locale;
  document.documentElement.lang = state.locale;
  document.documentElement.dir = state.locale === "fa" ? "rtl" : "ltr";
  $$('[data-i18n]').forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  $$('[data-i18n-placeholder]').forEach((element) => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });
  $$('[data-i18n-title]').forEach((element) => {
    const label = t(element.dataset.i18nTitle);
    element.title = label;
    if (element.matches("button")) element.setAttribute("aria-label", label);
  });
  $$('[data-i18n-aria-label]').forEach((element) => {
    element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel));
  });
  editorAdapter?.setAriaLabel?.(t("markdownEditor"));
  editorAdapter?.setLocale?.(state.locale);
  const localeSetting = $("#setting-locale");
  if (localeSetting) localeSetting.value = state.locale;
  renderPresets();
  renderRecents();
  renderWorkspace();
  // The settings browser is built from translated strings, so it is rebuilt
  // rather than patched when the interface language changes.
  renderAdvancedOptions();
  renderSummary();
  renderTemplateGallery();
  if (modalManager?.isOpen($("#command-modal"))) renderCommandPalette();
}

function showView(name) {
  $$(".view").forEach((element) => element.classList.remove("active"));
  $(`#${name}-view`)?.classList.add("active");
  document.body.dataset.view = name;
  if (name === "workspace") applyWorkspaceLayout();
  $("#app-main")?.focus({ preventScroll: true });
}


/**
 * Map a Markdown image path to a URL the webview may load.
 *
 * Only paths that resolve inside the open document's own directory are turned
 * into asset URLs; the native side allows exactly that directory and nothing
 * below it. Remote and absolute-URL sources are declined here rather than
 * fetched, which keeps the offline guarantee the app makes on its own footer.
 */
function resolveEditorAsset(source) {
  const raw = String(source || "").trim();
  if (!raw || /^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith("//")) return null;
  const model = activeDocument();
  if (!model?.path) return null;
  const separator = model.path.includes("\\") ? "\\" : "/";
  const directory = model.path.slice(0, model.path.lastIndexOf(separator));
  if (!directory) return null;

  const normalized = raw.replaceAll("\\", "/");
  // A path that climbs out of the document directory is outside the scope the
  // native side allowed, so it would fail to load anyway.
  if (normalized.split("/").includes("..")) return null;
  const absolute = normalized.startsWith("/")
    ? normalized
    : `${directory}${separator}${normalized}`;
  try {
    return globalThis.__TAURI__?.core?.convertFileSrc?.(absolute) || null;
  } catch {
    return null;
  }
}

/**
 * Apply the current view mode.
 *
 * The mode is the single source of truth for two things that used to be
 * toggled apart: whether the editor renders formatting, and whether the engine
 * preview pane is on screen. Write is the default because the app is for
 * writing; Split is for checking the published result against the source.
 */
function applyViewMode() {
  const mode = state.preferences.viewMode;
  editorAdapter?.setMode?.(editorModeForView(mode));

  const showPreview = previewVisibleForView(mode);
  if (state.workspaceLayout.previewOpen !== showPreview) {
    state.workspaceLayout = { ...state.workspaceLayout, previewOpen: showPreview };
    applyWorkspaceLayout({ persist: true });
  }

  for (const button of $$("[data-view-mode]")) {
    const selected = button.dataset.viewMode === mode;
    button.setAttribute("aria-checked", String(selected));
    button.classList.toggle("selected", selected);
  }
  const surface = $(".editor-pane");
  if (surface) surface.dataset.viewMode = mode;
  if (showPreview) schedulePreview(120);
}

function setViewMode(mode) {
  if (state.preferences.viewMode === mode) return;
  updatePreference({ viewMode: mode });
  editorAdapter?.focus?.();
}

function applyInterfacePreferences({ persist = false } = {}) {
  if (persist) state.preferences = writePreferences(state.preferences);
  state.preferences = applyPreferences(document.documentElement, state.preferences);
  // The editor keeps its own light/dark state so CodeMirror's floating panels
  // match the workspace.
  editorAdapter?.setTheme?.(document.documentElement.dataset.theme);
  editorAdapter?.setTypewriter?.(state.preferences.typewriter);
  applyViewMode();
  const autoPreview = $("#auto-preview");
  if (autoPreview) autoPreview.checked = Boolean(state.preferences.autoPreview);
}

function updatePreference(next, { persist = true } = {}) {
  state.preferences = { ...state.preferences, ...next };
  if (persist) state.preferences = writePreferences(state.preferences);
  applyInterfacePreferences();
}

function applyWorkspaceLayout({ persist = false } = {}) {
  const grid = $(".authoring-grid");
  const workspace = $("#workspace-view");
  if (!grid || !workspace) return;
  if (persist) state.workspaceLayout = writeWorkspaceLayout(state.workspaceLayout);
  for (const element of [workspace, grid]) {
    element.dataset.sidebarOpen = String(state.workspaceLayout.sidebarOpen);
    element.dataset.previewOpen = String(state.workspaceLayout.previewOpen);
    element.style.setProperty("--sidebar-width", `${state.workspaceLayout.sidebarWidth}px`);
    element.style.setProperty("--preview-width", `${state.workspaceLayout.previewWidth}px`);
  }
  const sidebarButton = $("#workspace-toggle-sidebar");
  const sidebarResizer = $("#sidebar-resizer");
  const previewResizer = $("#preview-resizer");
  if (sidebarButton) sidebarButton.setAttribute("aria-pressed", String(state.workspaceLayout.sidebarOpen));
  if (sidebarResizer) sidebarResizer.setAttribute("aria-valuenow", String(state.workspaceLayout.sidebarWidth));
  if (previewResizer) previewResizer.setAttribute("aria-valuenow", String(state.workspaceLayout.previewWidth));
}

function toggleWorkspacePane(name) {
  const key = name === "sidebar" ? "sidebarOpen" : "previewOpen";
  state.workspaceLayout = { ...state.workspaceLayout, [key]: !state.workspaceLayout[key] };
  applyWorkspaceLayout({ persist: true });
  if (name === "preview" && state.workspaceLayout.previewOpen) schedulePreview(80);
}

function setWorkspacePaneWidth(name, value, { persist = false } = {}) {
  const key = name === "sidebar" ? "sidebarWidth" : "previewWidth";
  state.workspaceLayout = {
    ...state.workspaceLayout,
    [key]: clampWorkspaceWidth(name, value),
  };
  applyWorkspaceLayout({ persist });
}

function beginPaneResize(event, name) {
  if (event.button !== 0 || matchMedia("(max-width: 1120px)").matches) return;
  event.preventDefault();
  const handle = event.currentTarget;
  const startX = event.clientX;
  const startWidth = name === "sidebar"
    ? state.workspaceLayout.sidebarWidth
    : state.workspaceLayout.previewWidth;
  handle.classList.add("is-dragging");
  handle.setPointerCapture?.(event.pointerId);
  const move = (moveEvent) => {
    const delta = moveEvent.clientX - startX;
    setWorkspacePaneWidth(name, name === "sidebar" ? startWidth + delta : startWidth - delta);
  };
  const end = () => {
    handle.classList.remove("is-dragging");
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", end);
    handle.removeEventListener("pointercancel", end);
    state.workspaceLayout = writeWorkspaceLayout(state.workspaceLayout);
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
}

function resizePaneWithKeyboard(event, name) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const current = name === "sidebar"
    ? state.workspaceLayout.sidebarWidth
    : state.workspaceLayout.previewWidth;
  let next = current;
  if (event.key === "ArrowLeft") next += name === "sidebar" ? -16 : 16;
  if (event.key === "ArrowRight") next += name === "sidebar" ? 16 : -16;
  if (event.key === "Home") next = name === "sidebar" ? 248 : 340;
  if (event.key === "End") next = name === "sidebar" ? 420 : 760;
  setWorkspacePaneWidth(name, next, { persist: true });
}

function renderTemplateGallery() {
  const container = $("#template-grid");
  if (!container) return;
  container.replaceChildren();
  for (const template of templateList()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "template-card";
    button.dataset.templateId = template.id;
    button.innerHTML = "<i></i><span><strong></strong><small></small></span>";
    button.querySelector("i").textContent = template.icon;
    button.querySelector("strong").textContent = t(template.titleKey);
    button.querySelector("small").textContent = t(template.descriptionKey);
    button.addEventListener("click", () => createDocumentFromTemplate(template.id));
    container.append(button);
  }
}

function createDocumentFromTemplate(templateId = "blank") {
  const metadata = templateList().find((item) => item.id === templateId) || templateList()[0];
  const model = createDocument({ content: templateContent(templateId, state.locale) });
  model.title = t(metadata.titleKey);
  state.documents.push(model);
  state.activeDocumentId = model.id;
  showView("workspace");
  renderWorkspace();
  scheduleRecovery();
  schedulePreview(100);
  currentEditor().focus();
  toast(t("templateCreated"), "success");
  return model;
}

function fillSettingsForm() {
  $("#setting-theme").value = state.preferences.theme;
  $("#setting-content-scale").value = state.preferences.contentScale;
  $("#setting-motion").value = state.preferences.reducedMotion;
  $("#setting-auto-preview").checked = state.preferences.autoPreview;
  $("#setting-typewriter").checked = state.preferences.typewriter;
  $("#setting-focus-mode").checked = state.preferences.focusMode;
  $("#setting-locale").value = state.locale;
  $("#settings-search").value = "";
  filterSettings("");
}

function openSettings() {
  fillSettingsForm();
  modalManager.open($("#settings-modal"), { initialFocus: "#settings-search" });
}

function closeSettings() {
  modalManager.close($("#settings-modal"));
}

function filterSettings(query = $("#settings-search")?.value || "") {
  const needle = String(query).trim().toLocaleLowerCase();
  let visible = 0;
  $$(".settings-section").forEach((section) => {
    const haystack = `${section.dataset.settingsTerms || ""} ${section.textContent || ""}`.toLocaleLowerCase();
    const show = !needle || haystack.includes(needle);
    section.classList.toggle("hidden", !show);
    if (show) visible += 1;
  });
  $("#settings-empty")?.classList.toggle("hidden", visible > 0);
  return visible;
}

function submitSettings(event) {
  event.preventDefault();
  state.preferences = writePreferences({
    ...state.preferences,
    theme: $("#setting-theme").value,
    contentScale: $("#setting-content-scale").value,
    reducedMotion: $("#setting-motion").value,
    autoPreview: $("#setting-auto-preview").checked,
    typewriter: $("#setting-typewriter").checked,
    focusMode: $("#setting-focus-mode").checked,
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
  toast(t("settingsReset"), "success");
}

function openHelp() {
  modalManager.open($("#help-modal"), { initialFocus: "#help-done" });
}

function closeHelp() {
  modalManager.close($("#help-modal"));
}

async function saveSupportBundle() {
  try {
    const path = await invoke("pick_support_bundle_output");
    if (!path) {
      toast(t("supportBundleCancelled"));
      return;
    }
    const id = requestId("support");
    const result = await invoke("sidecar_request", {
      request_id: id,
      method: "system.support_bundle",
      params: { output_path: path },
    });
    toast(`${t("supportBundleSaved")} ${result?.output_path || path}`, "success");
  } catch (error) {
    toast(errorText(error), "error");
  }
}


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
    $("#update-state").textContent = t("updateInstalling");
    const total = Number(state.updateTotal) || 0;
    const downloaded = Number(state.updateDownloaded) || 0;
    const percent = total > 0 ? Math.min(100, Math.round((downloaded / total) * 100)) : 0;
    $("#update-progress-bar").style.width = `${percent}%`;
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
  state.updateInstalling = true;
  state.updateDownloaded = 0;
  state.updateTotal = 0;
  updateUi();
  try {
    await installUpdate(state.updateCheck.version);
    state.updateInstalling = false;
    updateUi();
    toast(t("updateInstalled"), "success");
  } catch (error) {
    state.updateInstalling = false;
    $("#update-state").dataset.state = "error";
    $("#update-state").textContent = t("updateInstallFailed");
    $("#update-detail").textContent = errorText(error);
    $("#check-updates").disabled = false;
    $("#install-update").disabled = false;
  }
}

function renderOnboardingIntent() {
  const presentation = onboardingIntentPresentation(state.onboardingIntent);
  const container = $("#onboarding-intent-summary");
  if (!container) return;
  container.classList.toggle("hidden", !presentation);
  if (!presentation) return;
  $("#onboarding-intent-icon").textContent = presentation.icon;
  $("#onboarding-intent-title").textContent = t(presentation.titleKey);
  $("#onboarding-intent-detail").textContent = t(presentation.detailKey);
}

function setOnboardingStep(step) {
  state.onboardingStep = Math.max(0, Math.min(2, Number(step) || 0));
  $$("[data-onboarding-step]").forEach((section) => {
    section.classList.toggle("hidden", Number(section.dataset.onboardingStep) !== state.onboardingStep);
  });
  $$("[data-onboarding-dot]").forEach((dot) => {
    dot.classList.toggle("active", Number(dot.dataset.onboardingDot) <= state.onboardingStep);
  });
  $("#onboarding-back").classList.toggle("hidden", state.onboardingStep === 0);
  $("#onboarding-next").textContent = t(onboardingPrimaryActionKey(state.onboardingStep, state.onboardingIntent));
  renderOnboardingIntent();
}

function openOnboarding({ force = false } = {}) {
  if (!force && state.preferences.onboardingComplete) return false;
  state.onboardingIntent = null;
  setOnboardingStep(0);
  modalManager.open($("#onboarding-modal"), { initialFocus: "[data-onboarding-action='document']" });
  return true;
}

function completeOnboarding({ runIntent = false } = {}) {
  const intent = state.onboardingIntent;
  state.preferences = writePreferences({ ...state.preferences, onboardingComplete: true });
  applyInterfacePreferences();
  modalManager.close($("#onboarding-modal"));
  toast(t("tourCompleted"), "success");
  if (runIntent && intent === "document") createDocumentFromTemplate("blank");
  if (runIntent && intent === "book") openNewBookModal();
}

function onboardingNext() {
  if (state.onboardingStep < 2) {
    setOnboardingStep(state.onboardingStep + 1);
    return;
  }
  completeOnboarding({ runIntent: Boolean(state.onboardingIntent) });
}

function onboardingBack() {
  if (state.onboardingStep > 0) setOnboardingStep(state.onboardingStep - 1);
}

function commandDefinitions() {
  const hasDocument = Boolean(activeDocument());
  return [
    { id: "new", icon: "＋", label: t("commandNewDocument"), keywords: "new document markdown", shortcut: "Ctrl N", priority: 100, run: () => createUntitledDocument() },
    { id: "open", icon: "↗", label: t("commandOpenDocument"), keywords: "open file markdown", shortcut: "Ctrl O", priority: 95, run: () => chooseAuthoringFiles() },
    { id: "project", icon: "P", label: t("commandOpenProject"), keywords: "open folder workspace project", priority: 80, run: () => chooseProjectDirectory() },
    { id: "book", icon: "B", label: t("commandNewBook"), keywords: "book thesis chapters project", priority: 75, run: () => openNewBookModal() },
    { id: "save", icon: "✓", label: t("commandSave"), keywords: "save write", shortcut: "Ctrl S", priority: 90, enabled: hasDocument, run: () => saveActiveDocument() },
    { id: "save-as", icon: "⇩", label: t("commandSaveAs"), keywords: "save as copy", shortcut: "Ctrl Shift S", priority: 70, enabled: hasDocument, run: () => saveActiveDocument({ saveAs: true }) },
    { id: "validate", icon: "⌁", label: t("commandValidate"), keywords: "check problems diagnostics", priority: 65, enabled: hasDocument, run: () => validateActiveDocument() },
    { id: "export", icon: "PDF", label: t("commandExport"), keywords: "pdf publish render", priority: 85, enabled: hasDocument, run: () => exportActiveDocument() },
    { id: "find", icon: "⌕", label: t("commandFind"), keywords: "find replace search", shortcut: "Ctrl F", priority: 60, enabled: hasDocument, run: () => openFind({ replace: false }) },
    { id: "settings", icon: "⚙", label: t("commandSettings"), keywords: "preferences appearance accessibility", priority: 40, run: () => openSettings() },
    { id: "support-bundle", icon: "ZIP", label: t("commandSupportBundle"), keywords: "support diagnostics troubleshooting zip privacy", priority: 38, run: () => saveSupportBundle() },
    { id: "updates", icon: "↑", label: t("commandCheckUpdates"), keywords: "update upgrade release version", priority: 37, run: () => { openSettings(); setTimeout(() => checkUpdates(), 0); } },
    { id: "view-write", icon: "\u270e", label: t("viewWrite"), keywords: "write live formatted wysiwyg نوشتن", priority: 42, run: () => setViewMode("write") },
    { id: "view-source", icon: "</>", label: t("viewSource"), keywords: "source raw markdown سورس", priority: 41, run: () => setViewMode("source") },
    { id: "view-split", icon: "\u25eb", label: t("viewSplit"), keywords: "split preview compare دوستونه پیش نمایش", priority: 40, run: () => setViewMode("split") },
    { id: "typewriter", icon: "≡", label: t("typewriterMode"), keywords: "typewriter scroll centre writing ماشین تحریر", priority: 39, run: () => updatePreference({ typewriter: !state.preferences.typewriter }) },
    { id: "focus-mode", icon: "□", label: t("focusMode"), keywords: "focus distraction free zen تمرکز", priority: 39, run: () => updatePreference({ focusMode: !state.preferences.focusMode }) },
    { id: "help", icon: "?", label: t("commandHelp"), keywords: "help shortcuts guide onboarding", shortcut: "F1", priority: 35, run: () => openHelp() },
    { id: "home", icon: "⌂", label: t("commandHome"), keywords: "start home center", priority: 20, run: () => showView("start") },
  ];
}

function highlightCommand(index) {
  const length = state.visibleCommands.length;
  if (!length) {
    state.commandIndex = 0;
    return;
  }
  state.commandIndex = Math.max(0, Math.min(length - 1, Number(index) || 0));
  $$("#command-list .command-item").forEach((item, itemIndex) => {
    const active = itemIndex === state.commandIndex;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  const active = $("#command-list .command-item.active");
  if (active) $("#command-query").setAttribute("aria-activedescendant", active.id);
  else $("#command-query").removeAttribute("aria-activedescendant");
  $("#command-list .command-item.active")?.scrollIntoView?.({ block: "nearest" });
}

function renderCommandPalette() {
  const query = $("#command-query")?.value || "";
  state.visibleCommands = filterCommands(commandDefinitions(), query, 12);
  state.commandIndex = Math.max(0, Math.min(state.commandIndex, Math.max(0, state.visibleCommands.length - 1)));
  const container = $("#command-list");
  container.replaceChildren();
  if (!state.visibleCommands.length) {
    $("#command-query").removeAttribute("aria-activedescendant");
    const empty = document.createElement("div");
    empty.className = "command-empty";
    empty.textContent = t("noCommands");
    container.append(empty);
    return;
  }
  state.visibleCommands.forEach((command, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `command-item${index === state.commandIndex ? " active" : ""}`;
    button.dataset.commandId = command.id;
    button.id = `command-option-${command.id}`;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(index === state.commandIndex));
    button.innerHTML = "<i></i><span><strong></strong></span><kbd></kbd>";
    button.querySelector("i").textContent = command.icon || "•";
    button.querySelector("strong").textContent = command.label;
    const shortcut = button.querySelector("kbd");
    shortcut.textContent = command.shortcut || "";
    shortcut.classList.toggle("hidden", !command.shortcut);
    button.addEventListener("mouseenter", () => highlightCommand(index));
    button.addEventListener("click", () => runCommand(command));
    container.append(button);
  });
  container.querySelector(".command-item.active")?.scrollIntoView?.({ block: "nearest" });
  const active = container.querySelector(".command-item.active");
  if (active) $("#command-query").setAttribute("aria-activedescendant", active.id);
}

function openCommandPalette() {
  if (modalManager.hasOpenModal()) return;
  state.commandIndex = 0;
  $("#command-query").value = "";
  renderCommandPalette();
  $("#command-query").setAttribute("aria-expanded", "true");
  modalManager.open($("#command-modal"), {
    initialFocus: "#command-query",
    onClose: resetCommandPaletteA11y,
  });
}

function resetCommandPaletteA11y() {
  $("#command-query").setAttribute("aria-expanded", "false");
  $("#command-query").removeAttribute("aria-activedescendant");
}

function closeCommandPalette() {
  modalManager.close($("#command-modal"));
}

async function runCommand(command = state.visibleCommands[state.commandIndex]) {
  if (!command) return;
  closeCommandPalette();
  try {
    await command.run?.();
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function commandKeydown(event) {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const direction = event.key === "ArrowDown" ? 1 : -1;
    const length = state.visibleCommands.length;
    if (length) highlightCommand((state.commandIndex + direction + length) % length);
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    runCommand();
  }
}

function toast(message, kind = "info") {
  const element = document.createElement("div");
  element.className = `toast ${kind}`;
  element.setAttribute("role", kind === "error" ? "alert" : "status");
  element.setAttribute("aria-atomic", "true");
  element.textContent = message;
  $("#toast-region").append(element);
  setTimeout(() => element.remove(), 4200);
}

function errorPayload(error) {
  const raw = typeof error === "string" ? error : error?.message || String(error);
  try {
    const parsed = JSON.parse(raw);
    return parsed?.data || parsed?.error?.data || parsed;
  } catch {
    return { message: raw };
  }
}

function errorText(error) {
  const raw = typeof error === "string" ? error : error?.message || String(error);
  if (raw === "TAURI_UNAVAILABLE") return t("noTauri");
  try {
    const parsed = JSON.parse(raw);
    return parsed.message || parsed.error?.message || parsed.data?.message || raw;
  } catch {
    return raw;
  }
}

// ---------------------------------------------------------------------------
// Start Center and Quick Export
// ---------------------------------------------------------------------------
function setExportStatus(kind, titleKey, message, diagnostics = []) {
  const visual = $("#status-visual");
  visual.dataset.state = kind;
  $("#status-title").textContent = titleKey ? t(titleKey) : "";
  $("#status-message").textContent = message || "";
  const container = $("#diagnostics");
  container.replaceChildren();
  if (diagnostics.length) {
    container.classList.remove("hidden");
    for (const diagnostic of diagnostics.slice(0, 20)) {
      const item = document.createElement("div");
      item.className = `diagnostic ${diagnostic.severity || "info"}`;
      const location = diagnostic.line ? ` · ${diagnostic.line}:${diagnostic.column || 1}` : "";
      item.textContent = `${diagnostic.code || ""}${location} — ${diagnostic.message || ""}`;
      container.append(item);
    }
  } else {
    container.classList.add("hidden");
  }
}

function working(enabled, mode = "render") {
  $("#validate-button").disabled = enabled;
  $("#export-button").disabled = enabled;
  $("#cancel-button").classList.toggle("hidden", !enabled);
  $("#progress-wrap").classList.toggle("hidden", !enabled);
  if (enabled) {
    $("#progress-bar").style.width = "3%";
    $("#progress-label").textContent = "3%";
    setExportStatus("working", mode === "validate" ? "validatingTitle" : "renderingTitle", t(mode === "validate" ? "validatingMessage" : "renderingMessage"));
  }
}

/**
 * Values the user has typed into the settings panel, keyed by option.
 *
 * Absent means "inherit"; the panel never sends a key the user did not touch,
 * so opening it cannot overwrite what mardas.toml already configured.
 */
const advancedValues = new Map();

/** Which category the settings browser is showing. */
let activeOptionGroup = OPTION_GROUPS[0].id;
let optionSearchQuery = "";
let showExpertOptions = false;

/**
 * The accent each palette prints with.
 *
 * Mirrored from `appearance.PALETTES` so choosing a palette is a colour
 * decision made against colour, not against seven English words.
 * `tests/test_desktop_app.py` holds these against the engine's own table.
 */
const PALETTE_ACCENTS = Object.freeze({
  blue: "#2563eb",
  emerald: "#047857",
  violet: "#7c3aed",
  amber: "#b45309",
  rose: "#e11d48",
  slate: "#475569",
  neutral: "#404040",
});

function advancedControlId(key) {
  return `adv-${key.replaceAll("_", "-")}`;
}

/** A translated label for an engine enum value, falling back to the identifier. */
function choiceLabel(value) {
  const label = t(value);
  return label === value ? value : label;
}

function setOptionValue(key, value) {
  if (value === undefined) advancedValues.delete(key);
  else advancedValues.set(key, value);
  renderOptionRail();
  renderOptionPane();
  renderSummary();
  schedulePdfPreview();
}

/**
 * The three states every boolean option really has.
 *
 * A checkbox can only say on or off, so an unchecked box and an option the user
 * never touched looked identical — and sending "off" for an option the project
 * configuration had turned on is a silent override. The third state is the
 * default one, and it is shown as such.
 */
function buildToggleControl(field) {
  const group = document.createElement("div");
  group.className = "tri-toggle";
  group.setAttribute("role", "radiogroup");
  group.setAttribute("aria-labelledby", `${advancedControlId(field.key)}-label`);
  const current = advancedValues.has(field.key) ? Boolean(advancedValues.get(field.key)) : null;
  const states = [
    [null, t("inherit"), "—"],
    [false, t("off"), t("off")],
    [true, t("on"), t("on")],
  ];
  for (const [value, label, text] of states) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tri-toggle-option";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(current === value));
    button.setAttribute("aria-label", label);
    button.textContent = text;
    button.addEventListener("click", () => setOptionValue(field.key, value ?? undefined));
    group.append(button);
  }
  return group;
}

function buildSelectControl(field) {
  const control = document.createElement("select");
  control.id = advancedControlId(field.key);
  const inherit = document.createElement("option");
  inherit.value = "";
  inherit.textContent = `— ${t("inherit")}`;
  control.append(inherit);
  for (const choice of field.choices) {
    const option = document.createElement("option");
    option.value = choice;
    option.textContent = choiceLabel(choice);
    control.append(option);
  }
  control.value = advancedValues.has(field.key) ? String(advancedValues.get(field.key)) : "";
  control.addEventListener("change", () => {
    setOptionValue(field.key, control.value === "" ? undefined : control.value);
  });
  return control;
}

/** A palette is a colour decision, so it is made against colour. */
function buildSwatchControl(field) {
  const wrapper = document.createElement("div");
  wrapper.className = "swatch-row";
  wrapper.setAttribute("role", "radiogroup");
  wrapper.setAttribute("aria-labelledby", `${advancedControlId(field.key)}-label`);
  const current = advancedValues.get(field.key) ?? "";
  for (const choice of field.choices) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "swatch";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(current === choice));
    button.setAttribute("aria-label", choiceLabel(choice));
    button.title = choiceLabel(choice);
    button.style.setProperty("--swatch", PALETTE_ACCENTS[choice] || "#808080");
    button.addEventListener("click", () => {
      setOptionValue(field.key, current === choice ? undefined : choice);
    });
    wrapper.append(button);
  }
  return wrapper;
}

function buildSliderControl(field) {
  const wrapper = document.createElement("div");
  wrapper.className = "slider-row";
  const slider = document.createElement("input");
  slider.type = "range";
  slider.id = advancedControlId(field.key);
  slider.min = String(field.min ?? 0);
  slider.max = String(field.max ?? 1);
  slider.step = String(field.step ?? 0.05);
  const readout = document.createElement("output");
  const stored = advancedValues.get(field.key);
  slider.value = String(stored ?? field.max ?? 1);
  readout.textContent = stored === undefined ? "—" : String(stored);
  slider.addEventListener("input", () => {
    readout.textContent = slider.value;
  });
  slider.addEventListener("change", () => setOptionValue(field.key, Number(slider.value)));
  wrapper.append(slider, readout);
  return wrapper;
}

function buildTextControl(field) {
  const wrapper = document.createElement("div");
  wrapper.className = "text-row";
  const control = document.createElement("input");
  control.id = advancedControlId(field.key);
  control.type = field.kind === "number" ? "number" : "text";
  if (field.min !== undefined) control.min = String(field.min);
  if (field.max !== undefined) control.max = String(field.max);
  if (field.step !== undefined) control.step = String(field.step);
  if (field.placeholder) control.placeholder = field.placeholder;
  if (field.kind === "path") control.dir = "ltr";
  control.value = advancedValues.has(field.key) ? String(advancedValues.get(field.key)) : "";
  const problem = document.createElement("small");
  problem.className = "option-problem";

  const commit = () => {
    const raw = control.value.trim();
    const complaint = raw ? validateOptionValue(field.key, raw) : null;
    problem.textContent = complaint ? t(complaint) : "";
    control.setAttribute("aria-invalid", String(Boolean(complaint)));
    wrapper.classList.toggle("has-problem", Boolean(complaint));
    // An invalid value is kept in the control so it can be corrected, but it is
    // never sent to the engine, which would only fail the render later.
    if (complaint) {
      advancedValues.delete(field.key);
      renderSummary();
      return;
    }
    setOptionValue(field.key, raw === "" ? undefined : raw);
  };
  control.addEventListener("change", commit);

  wrapper.append(control);
  if (field.unit) {
    const unit = document.createElement("span");
    unit.className = "option-unit";
    unit.textContent = field.unit;
    wrapper.append(unit);
  }
  if (field.kind === "path") {
    const browse = document.createElement("button");
    browse.type = "button";
    browse.className = "button secondary compact";
    browse.textContent = t("browse");
    browse.addEventListener("click", async () => {
      const picked = await invoke(
        field.widget === "directory" ? "pick_project_directory" : "pick_document_asset",
      );
      if (!picked) return;
      control.value = picked;
      setOptionValue(field.key, picked);
    });
    wrapper.append(browse);
  }
  wrapper.append(problem);
  return wrapper;
}

function buildOptionControl(field) {
  if (field.kind === "toggle") return buildToggleControl(field);
  if (field.widget === "swatches") return buildSwatchControl(field);
  if (field.widget === "slider") return buildSliderControl(field);
  if (field.kind === "select") return buildSelectControl(field);
  return buildTextControl(field);
}

/**
 * One option: what it is, what it decides, and what it is set to.
 *
 * The help line is not decoration. Fifty-three identically-shaped controls
 * named after engine identifiers is a specification; a sentence saying what
 * each one changes is what makes it a setting someone can decide.
 */
function buildOptionRow(field, group) {
  const row = document.createElement("div");
  row.className = "option-row";
  row.dataset.optionKey = field.key;
  const isSet = advancedValues.has(field.key);
  row.dataset.modified = String(isSet);

  const head = document.createElement("div");
  head.className = "option-head";
  const label = document.createElement("label");
  label.className = "option-label";
  label.id = `${advancedControlId(field.key)}-label`;
  label.textContent = t(`opt.${field.key}`);
  if (field.kind !== "toggle" && field.widget !== "swatches") {
    label.setAttribute("for", advancedControlId(field.key));
  }
  head.append(label);

  if (field.risky) {
    const badge = document.createElement("span");
    badge.className = "option-badge risky";
    badge.textContent = t("riskyBadge");
    head.append(badge);
  }
  if (isSet) {
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "option-reset";
    reset.title = t("resetOption");
    reset.setAttribute("aria-label", `${t("resetOption")}: ${t(`opt.${field.key}`)}`);
    reset.textContent = "×";
    reset.addEventListener("click", () => setOptionValue(field.key, undefined));
    head.append(reset);
  }

  const help = document.createElement("p");
  help.className = "option-help";
  help.textContent = field.helpKey ? t(field.helpKey) : "";

  const active = fieldIsActive(field, Object.fromEntries(advancedValues), presetById(state.presetId).options);
  if (!active) {
    row.dataset.inactive = "true";
    const reason = document.createElement("p");
    reason.className = "option-inactive";
    reason.textContent = t("inactiveOption").replace("%s", t(`opt.${field.dependsOn}`));
    row.append(head, help, buildOptionControl(field), reason);
    if (group) row.dataset.group = group.id;
    return row;
  }

  row.append(head, help, buildOptionControl(field));
  if (group) row.dataset.group = group.id;
  return row;
}

/** Fields of a group the user should currently see. */
function visibleFields(group) {
  return group.fields.filter((field) => showExpertOptions || !field.expert);
}

function renderOptionRail() {
  const rail = $("#option-rail");
  if (!rail) return;
  const counts = modifiedCountsByGroup(
    Object.fromEntries(advancedValues),
    presetById(state.presetId).options,
  );
  rail.replaceChildren();
  for (const group of OPTION_GROUPS) {
    if (group.expert && !showExpertOptions) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "option-rail-item";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(group.id === activeOptionGroup && !optionSearchQuery));
    button.tabIndex = group.id === activeOptionGroup ? 0 : -1;
    button.dataset.group = group.id;

    const icon = document.createElement("span");
    icon.className = "option-rail-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = group.icon || "•";
    const name = document.createElement("span");
    name.className = "option-rail-name";
    name.textContent = t(group.labelKey);
    button.append(icon, name);

    if (counts[group.id]) {
      const badge = document.createElement("span");
      badge.className = "option-rail-badge";
      badge.textContent = String(counts[group.id]);
      badge.title = `${counts[group.id]} ${t("changedCount")}`;
      button.append(badge);
    }
    button.addEventListener("click", () => {
      activeOptionGroup = group.id;
      const search = $("#option-search");
      if (search) search.value = "";
      optionSearchQuery = "";
      renderOptionRail();
      renderOptionPane();
    });
    rail.append(button);
  }
}

function renderOptionPane() {
  const pane = $("#option-pane");
  if (!pane) return;
  pane.replaceChildren();

  if (optionSearchQuery) {
    const matches = (searchOptions(optionSearchQuery, t) || [])
      .filter(({ field, group }) => showExpertOptions || (!field.expert && !group.expert));
    if (!matches.length) {
      const empty = document.createElement("p");
      empty.className = "option-empty";
      empty.textContent = t("noOptionsMatch");
      pane.append(empty);
      return;
    }
    let lastGroup = null;
    for (const { group, field } of matches) {
      if (group !== lastGroup) {
        const caption = document.createElement("p");
        caption.className = "option-search-group";
        caption.textContent = t(group.labelKey);
        pane.append(caption);
        lastGroup = group;
      }
      pane.append(buildOptionRow(field, group));
    }
    return;
  }

  const group = OPTION_GROUPS.find((item) => item.id === activeOptionGroup) || OPTION_GROUPS[0];
  const header = document.createElement("header");
  header.className = "option-pane-head";
  const heading = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = t(group.labelKey);
  const description = document.createElement("small");
  description.textContent = group.descriptionKey ? t(group.descriptionKey) : "";
  heading.append(title, description);
  header.append(heading);

  const groupModified = modifiedCountsByGroup(
    Object.fromEntries(advancedValues),
    presetById(state.presetId).options,
  )[group.id];
  if (groupModified) {
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "text-button";
    reset.textContent = t("resetGroup");
    reset.addEventListener("click", () => {
      for (const field of group.fields) advancedValues.delete(field.key);
      renderOptionRail();
      renderOptionPane();
      renderSummary();
      schedulePdfPreview();
    });
    header.append(reset);
  }
  pane.append(header);

  const fields = visibleFields(group);
  for (const field of fields) pane.append(buildOptionRow(field, group));
  if (!fields.length) {
    const empty = document.createElement("p");
    empty.className = "option-empty";
    empty.textContent = t("noOptionsMatch");
    pane.append(empty);
  }
}

function renderAdvancedOptions() {
  renderOptionRail();
  renderOptionPane();
}

function resetAdvancedOptions() {
  advancedValues.clear();
  renderAdvancedOptions();
  renderSummary();
  schedulePdfPreview();
}

/**
 * Preview of the document as the chosen options will publish it.
 *
 * The engine composes the same page the exporter will print, with the same
 * option payload, so changing the palette or turning the contents off shows
 * here before a PDF is written. It is debounced because every keystroke in a
 * text option would otherwise start a render.
 */
let exportPreviewTimer = null;
let exportPreviewSequence = 0;
let exportPreviewRequestId = null;

/**
 * Stand the preview down before a job the user actually asked for.
 *
 * The engine runs one job at a time and answers a second with SERVER_BUSY, so
 * a preview still rendering when "Create PDF" is pressed would fail the export.
 * The preview is speculative work; it yields.
 */
async function releaseEngineForJob() {
  if (exportPreviewTimer) {
    clearTimeout(exportPreviewTimer);
    exportPreviewTimer = null;
  }
  exportPreviewSequence += 1;
  const pending = exportPreviewRequestId;
  exportPreviewRequestId = null;
  if (!pending) return;
  try {
    await invoke("sidecar_cancel", { request_id: pending });
  } catch {
    // Already finished, or never started; either way the engine is free.
  }
}

function setExportPreviewState(key) {
  const label = $("#export-preview-state");
  if (label) label.textContent = key ? t(key) : "";
}

function schedulePdfPreview(delay = 450) {
  // A job the user asked for owns the engine until it finishes.
  if (state.activeRequestId) return;
  if (exportPreviewTimer) clearTimeout(exportPreviewTimer);
  exportPreviewTimer = setTimeout(() => {
    exportPreviewTimer = null;
    void renderExportPreview();
  }, delay);
}

/** The paper deck, created the first time the export view needs it. */
let pageDeck = null;

function exportPreviewDeck() {
  const surface = $("#export-preview");
  if (!surface) return null;
  if (!pageDeck) pageDeck = createPageDeck(surface, { onState: renderPreviewToolbar });
  return pageDeck;
}

/**
 * Reflect the deck's state in its toolbar.
 *
 * The page count is the one number the export screen could never show before:
 * how long the document actually is once it is on paper.
 */
function renderPreviewToolbar(deckState) {
  const level = $("#preview-zoom-level");
  if (level) level.textContent = `${Math.round((deckState.zoom || 1) * 100)}%`;
  const counter = $("#preview-page-count");
  if (counter) {
    counter.textContent = deckState.pageCount
      ? `${deckState.currentPage} / ${deckState.pageCount}`
      : "—";
  }
  $("#preview-fit-width")?.setAttribute("aria-pressed", String(deckState.zoomMode === "fit-width"));
  $("#preview-fit-page")?.setAttribute("aria-pressed", String(deckState.zoomMode === "fit-page"));
  $("#preview-guides")?.setAttribute("aria-pressed", String(Boolean(deckState.guides)));
  for (const id of ["#preview-prev-page", "#preview-next-page"]) {
    const button = $(id);
    if (button) button.disabled = deckState.pageCount < 2;
  }
}

function movePreviewPage(delta) {
  const deck = exportPreviewDeck();
  if (!deck?.pageCount) return;
  const counter = $("#preview-page-count");
  const current = Number(String(counter?.textContent || "1").split("/")[0].trim()) || 1;
  deck.goToPage(current + delta);
}

/**
 * A note under the preview for the one thing it cannot show.
 *
 * Equations are typeset by MathJax inside Chromium at export time. Rather than
 * silently showing TeX source and letting the user believe that is the output,
 * the preview says how many expressions are waiting.
 */
function renderPreviewNote(payload) {
  const note = $("#export-preview-note");
  if (!note) return;
  const pending = payload?.math?.typeset_at_export ? Number(payload.math.expressions) || 0 : 0;
  note.classList.toggle("hidden", pending < 1);
  note.textContent = pending < 1 ? "" : `${t("previewMathPending")} (${pending})`;
}

async function renderExportPreview() {
  const deck = exportPreviewDeck();
  if (!deck) return;
  if (!state.sourcePath) {
    setExportPreviewState("");
    renderPreviewNote(null);
    deck.showMessage(t("previewChooseSource"));
    return;
  }
  const sequence = (exportPreviewSequence += 1);
  setExportPreviewState("previewUpdating");
  const id = `export-preview-${sequence}-${Date.now()}`;
  exportPreviewRequestId = id;
  try {
    const file = await readDocument(state.sourcePath);
    const content = typeof file === "string" ? file : String(file?.content ?? "");
    if (sequence !== exportPreviewSequence) return;
    const result = await previewDocumentPage({
      path: state.sourcePath,
      content,
      options: exportOverrides(),
      requestId: id,
    });
    if (sequence !== exportPreviewSequence) return;
    deck.render(result);
    renderPreviewNote(result);
    setExportPreviewState("");
  } catch (error) {
    if (sequence !== exportPreviewSequence) return;
    setExportPreviewState("previewFailedShort");
    const payload = errorPayload(error);
    renderPreviewNote(null);
    deck.showMessage(payload?.message || t("previewFailed"));
  } finally {
    if (exportPreviewRequestId === id) exportPreviewRequestId = null;
  }
}

/**
 * The overrides this export will send.
 *
 * One control per option. Page size, appearance, language and contents used to
 * exist twice — once in a "basic settings" strip and again in the settings
 * panel — so the same value had two widgets that could disagree, and which one
 * won depended on merge order rather than on anything the user could see.
 */
function exportOverrides() {
  return collectRenderOptions(Object.fromEntries(advancedValues));
}

function renderPresets() {
  const grid = $("#preset-grid");
  if (!grid) return;
  grid.replaceChildren();
  for (const preset of Object.values(PRESETS)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `preset-card${preset.id === state.presetId ? " selected" : ""}`;
    button.dataset.preset = preset.id;
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(preset.id === state.presetId));
    button.innerHTML = `<strong></strong><small></small><i aria-hidden="true">✓</i>`;
    button.querySelector("strong").textContent = t(preset.titleKey);
    button.querySelector("small").textContent = t(preset.descriptionKey);
    button.addEventListener("click", () => selectPreset(preset.id));
    grid.append(button);
  }
}

/**
 * Apply a preset by seeding the settings panel with its values.
 *
 * The preset is a starting point the user can then adjust in place, so its
 * choices have to be visible in the same controls they would use to change
 * them — not held invisibly behind the card.
 */
function selectPreset(id) {
  const preset = presetById(id);
  state.presetId = preset.id;
  advancedValues.clear();
  for (const [key, value] of Object.entries(preset.options)) {
    if (key in OPTION_FIELDS) advancedValues.set(key, value);
  }
  renderAdvancedOptions();
  renderPresets();
  renderSummary();
  schedulePdfPreview();
}

/**
 * What this export will actually do, in four lines.
 *
 * The summary answers the question a settings panel cannot: after all those
 * decisions, what am I about to produce. The last row counts what has been
 * changed away from the preset, because that is the part worth double-checking.
 */
function renderSummary() {
  const container = $("#preset-summary");
  if (!container) return;
  const preset = presetById(state.presetId);
  const options = { ...preset.options, ...exportOverrides() };
  const changed = modifiedKeys(Object.fromEntries(advancedValues), preset.options).length;
  const rows = [
    [t("preset"), t(preset.titleKey)],
    [t("page"), options.page_size || "A4"],
    [t("toc"), options.toc ? t("enabled") : t("disabled")],
    [t("quality"), options.quality_profile === "strict-publication" ? t("strict") : t("standard")],
    [t("settingsSummary"), changed ? `${changed} ${t("changedCount")}` : t("noChanges")],
  ];
  container.replaceChildren(...rows.map(([label, value]) => {
    const row = document.createElement("div");
    row.className = "summary-row";
    const caption = document.createElement("span");
    caption.textContent = label;
    const detail = document.createElement("strong");
    detail.textContent = String(value);
    row.append(caption, detail);
    return row;
  }));
}

function renderRecents() {
  const list = $("#recent-list");
  if (!list) return;
  list.replaceChildren();
  $("#recent-empty").classList.toggle("hidden", state.recents.length > 0);
  for (const recent of state.recents) {
    const button = document.createElement("button");
    button.className = "recent-item";
    button.type = "button";
    button.innerHTML = `<span>MD</span><div class="recent-copy"><strong></strong><small></small></div><b class="recent-arrow" aria-hidden="true">←</b>`;
    button.querySelector("strong").textContent = basename(recent.path);
    button.querySelector("small").textContent = recent.path;
    button.addEventListener("click", () => openAuthoringPaths([recent.path]));
    list.append(button);
  }
}

function saveRecent(path) {
  if (!path) return;
  state.recents = writeRecents(addRecent(state.recents, path));
  renderRecents();
}

function hideExportResult() {
  state.outputResult = null;
  $("#export-result")?.classList.add("hidden");
}

function showExportResult(path) {
  const resultPath = String(path || "").trim();
  const container = $("#export-result");
  if (!container || !resultPath) return;
  $("#export-result-name").textContent = basename(resultPath);
  $("#export-result-path").textContent = resultPath;
  container.classList.remove("hidden");
}

function openExportSource(path) {
  hideExportResult();
  state.sourcePath = path;
  state.outputPath = defaultOutputPath(path);
  $("#source-path").value = path;
  $("#output-path").value = state.outputPath;
  setExportStatus("idle", "readyTitle", t("readyMessage"));
  showView("export");
}

async function chooseExportSource() {
  try {
    const path = await invoke("pick_markdown_file");
    if (path) openExportSource(path);
  } catch (error) {
    toast(errorText(error), "error");
  }
}

async function chooseExportOutput() {
  if (!state.sourcePath) {
    toast(t("selectSourceFirst"), "error");
    return;
  }
  try {
    const path = await invoke("pick_pdf_output", { suggested_path: state.outputPath || defaultOutputPath(state.sourcePath) });
    if (path) {
      state.outputPath = path;
      $("#output-path").value = path;
    }
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function exportSelectionValid() {
  const errors = validateExportSelection({ sourcePath: state.sourcePath, outputPath: state.outputPath });
  if (!errors.length) return true;
  setExportStatus("error", "errorTitle", errors.map((code) => t(code)).join(" "));
  return false;
}

async function validateExportDocument() {
  if (!exportSelectionValid()) return;
  await releaseEngineForJob();
  working(true, "validate");
  const id = requestId("validate");
  state.activeRequestId = id;
  try {
    const params = buildDocumentParams({ sourcePath: state.sourcePath, outputPath: state.outputPath, presetId: state.presetId, overrides: exportOverrides() });
    const result = await invoke("sidecar_request", { request_id: id, method: "validate.document", params });
    const diagnostics = Array.isArray(result?.diagnostics) ? result.diagnostics : [];
    setExportStatus(result?.ok ? "success" : "error", result?.ok ? "validTitle" : "invalidTitle", t(result?.ok ? "validMessage" : "invalidMessage"), diagnostics);
  } catch (error) {
    setExportStatus("error", "errorTitle", errorText(error));
  } finally {
    state.activeRequestId = null;
    working(false);
  }
}

async function exportDocument(event) {
  event?.preventDefault();
  if (!exportSelectionValid()) return;
  await releaseEngineForJob();
  working(true);
  hideExportResult();
  const id = requestId("render");
  state.activeRequestId = id;
  try {
    const params = buildDocumentParams({ sourcePath: state.sourcePath, outputPath: state.outputPath, presetId: state.presetId, overrides: exportOverrides() });
    const result = await invoke("sidecar_request", { request_id: id, method: "render.document", params });
    state.outputResult = result;
    $("#progress-bar").style.width = "100%";
    $("#progress-label").textContent = "100%";
    const resultPath = result.output_path || state.outputPath;
    setExportStatus("success", "successTitle", t("successMessage"));
    showExportResult(resultPath);
    saveRecent(state.sourcePath);
  } catch (error) {
    const message = errorText(error);
    setExportStatus("error", "errorTitle", message);
    toast(message, "error");
  } finally {
    state.activeRequestId = null;
    working(false);
  }
}

async function cancelExport() {
  if (!state.activeRequestId) return;
  try {
    await invoke("sidecar_cancel", { request_id: state.activeRequestId });
    toast(t("operationCancelled"));
  } catch (error) {
    toast(errorText(error), "error");
  }
}

async function openResult(reveal) {
  const path = state.outputResult?.output_path || state.outputPath;
  if (!path) return;
  try {
    await invoke(reveal ? "reveal_path" : "open_path", { path });
  } catch (error) {
    toast(errorText(error), "error");
  }
}

// ---------------------------------------------------------------------------
// Authoring workspace
// ---------------------------------------------------------------------------
function persistSession() {
  writeSession(state.documents, activeDocument(), state.project?.path ?? null);
}

function tabElement(model) {
  const tab = window.document.createElement("div");
  tab.className = `document-tab${model.id === state.activeDocumentId ? " active" : ""}${documentDirty(model) ? " dirty" : ""}`;
  tab.dataset.documentId = model.id;
  tab.innerHTML = `<button class="tab-activate" type="button" role="tab"><i class="dirty-dot"></i><span class="tab-name"></span></button><button class="tab-close" type="button" aria-label="${t("close")}">×</button>`;
  tab.querySelector(".tab-name").textContent = model.title;
  const activate = tab.querySelector(".tab-activate");
  activate.tabIndex = model.id === state.activeDocumentId ? 0 : -1;
  activate.setAttribute("aria-selected", String(model.id === state.activeDocumentId));
  activate.addEventListener("click", () => activateDocument(model.id));
  activate.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activateDocument(model.id);
      return;
    }
    const index = state.documents.findIndex((item) => item.id === model.id);
    let target = null;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") target = state.documents[(index - 1 + state.documents.length) % state.documents.length];
    if (event.key === "ArrowRight" || event.key === "ArrowDown") target = state.documents[(index + 1) % state.documents.length];
    if (event.key === "Home") target = state.documents[0];
    if (event.key === "End") target = state.documents.at(-1);
    if (!target) return;
    event.preventDefault();
    activateDocument(target.id);
  });
  tab.querySelector(".tab-close").addEventListener("click", (event) => {
    event.stopPropagation();
    requestCloseDocument(model.id);
  });
  return tab;
}

function renderDocumentTabs() {
  const container = $("#document-tabs");
  if (!container) return;
  container.replaceChildren(...state.documents.map(tabElement));
}

function setSaveState(kind) {
  const element = $("#save-state");
  if (!element) return;
  element.dataset.state = kind;
  element.textContent = t(kind === "dirty" ? "unsaved" : kind === "saving" ? "saving" : "saved");
}

function updateLineGutter() {
  const editor = currentEditor();
  const gutter = $("#line-gutter");
  if (editorAdapter?.usesNativeLineNumbers) {
    gutter.hidden = true;
    return;
  }
  gutter.hidden = false;
  const lines = Math.max(1, editor.value.split("\n").length);
  gutter.textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
  gutter.scrollTop = editor.scrollTop;
}

function updateEditorMetrics() {
  const editor = currentEditor();
  const metrics = textMetrics(editor.value, editor.selectionStart);
  $("#cursor-status").textContent = `${t("lineShort")} ${metrics.line}, ${t("columnShort")} ${metrics.column}`;
  $("#word-status").textContent = `${metrics.words} ${t("wordsLabel")} · ${metrics.characters} ${t("charactersLabel")}`;
}

function renderOutline(model) {
  const outline = extractOutline(model?.content || "");
  $("#outline-count").textContent = String(outline.length);
  const list = $("#outline-list");
  list.replaceChildren();
  if (!outline.length) {
    list.innerHTML = `<div class="tool-empty">${t("noOutline")}</div>`;
    return;
  }
  for (const item of outline) {
    const button = document.createElement("button");
    button.className = "tool-item";
    button.type = "button";
    button.dataset.level = String(item.level);
    button.innerHTML = `<span class="level">H${item.level}</span><span></span>`;
    button.querySelector("span:last-child").textContent = item.title;
    button.addEventListener("click", () => goToLine(item.line));
    list.append(button);
  }
}

function loadFrontMatterForm(model) {
  const form = $("#frontmatter-form");
  const fields = parseFrontMatter(model?.content || "").fields;
  for (const name of ["title", "subtitle", "author", "lang", "dir"]) {
    const input = form.elements.namedItem(name);
    if (input) input.value = fields[name] ?? (name === "lang" || name === "dir" ? "auto" : "");
  }
  form.elements.namedItem("toc").checked = Boolean(fields.toc);
}

function renderCitations(model) {
  const used = extractCitationKeys(model?.content || "");
  if (state.project?.path && model?.projectPath === state.project.path) {
    renderBibliographyEntries(state.bibliographyEntries, used);
    return;
  }
  const entries = Array.isArray(model?.preview?.document?.citation_entries) ? model.preview.document.citation_entries : [];
  const entryKeys = entries.map((entry) => entry.key || entry.id || entry.citation_key).filter(Boolean);
  const keys = [...new Set([...used, ...entryKeys])].sort((a, b) => String(a).localeCompare(String(b)));
  $("#citation-count").textContent = String(keys.length);
  const list = $("#citation-list");
  list.replaceChildren();
  if (!keys.length) {
    list.innerHTML = `<div class="tool-empty">${t("noCitations")}</div>`;
    return;
  }
  for (const key of keys) {
    const button = document.createElement("button");
    button.className = "tool-item";
    button.type = "button";
    button.innerHTML = `<span class="citation-key"></span><small></small>`;
    button.querySelector(".citation-key").textContent = `@${key}`;
    button.querySelector("small").textContent = used.includes(key) ? "used" : "library";
    button.addEventListener("click", () => insertAtCursor(`[@${key}]`));
    list.append(button);
  }
}

function renderProblems(model) {
  const diagnostics = [
    ...(Array.isArray(model?.diagnostics) ? model.diagnostics : []),
    ...(Array.isArray(model?.bibliographyDiagnostics) ? model.bibliographyDiagnostics : []),
    ...(model?.projectPath === state.project?.path && Array.isArray(state.projectDiagnostics)
      ? state.projectDiagnostics
      : []),
  ];
  editorAdapter?.setDiagnostics?.(inlineDiagnosticsForDocument(diagnostics, model));
  $("#problem-count").textContent = String(diagnostics.length);
  const problemBadge = $("#sidebar-problem-badge");
  if (problemBadge) {
    problemBadge.textContent = diagnostics.length > 99 ? "99+" : String(diagnostics.length);
    problemBadge.classList.toggle("hidden", diagnostics.length === 0);
  }
  const list = $("#problem-list");
  list.replaceChildren();
  if (!diagnostics.length) {
    list.innerHTML = `<div class="tool-empty">${t("noProblems")}</div>`;
    return;
  }
  for (const diagnostic of diagnostics) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tool-item problem-${diagnostic.severity || "info"}`;
    button.innerHTML = `<span class="level"></span><span></span>`;
    button.querySelector(".level").textContent = diagnostic.code || "!";
    button.querySelector("span:last-child").textContent = diagnostic.message || String(diagnostic);
    if (diagnostic.path && state.project?.path) {
      button.addEventListener("click", () =>
        openProjectRelativeFile(diagnostic.path, {
          line: diagnostic.line || 1,
          column: diagnostic.column || 1,
        })
      );
    } else if (diagnostic.line) {
      button.addEventListener("click", () => goToLine(diagnostic.line, diagnostic.column || 1));
    }
    list.append(button);
  }
}

function renderAssets(items = []) {
  const list = $("#asset-list");
  list.replaceChildren();
  if (!items.length) {
    list.innerHTML = `<div class="tool-empty">${t("noAssets")}</div>`;
    return;
  }
  for (const asset of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tool-item";
    button.innerHTML = `<span class="asset-kind"></span><span></span>`;
    button.querySelector(".asset-kind").textContent = String(asset.extension || "file").replace(".", "");
    button.querySelector("span:last-child").textContent = asset.relative_path || asset.name;
    button.addEventListener("click", () => insertAssetReference(asset));
    list.append(button);
  }
}

function updateAuthoringMode(model) {
  const hasDocument = Boolean(model);
  const markdown = isMarkdownModel(model);
  const editable = hasDocument && !model.readOnly;
  $("#workspace-save").disabled = !editable;
  $("#workspace-save-as").disabled = !hasDocument;
  for (const element of $$('[data-editor-command], #workspace-import-asset, #import-asset, #refresh-assets')) {
    element.disabled = !editable || !markdown;
  }
  for (const selector of ["#workspace-validate", "#workspace-export", "#refresh-preview", "#auto-preview"]) {
    $(selector).disabled = !hasDocument || !markdown;
  }
  for (const name of ["frontmatter", "assets", "citations"]) {
    const button = $(`[data-sidebar="${name}"]`);
    if (button) button.disabled = !hasDocument || !markdown;
  }
  $("#frontmatter-form")?.querySelectorAll("input,select,button").forEach((element) => {
    element.disabled = !editable || !markdown;
  });
  $("#workspace-view")?.classList.toggle("plain-text-mode", hasDocument && !markdown);
}

function renderWorkspace() {
  const model = activeDocument();
  renderDocumentTabs();
  const editor = currentEditor();
  renderProjectWorkspace();
  renderBookWorkspace();
  if (!model) {
    editor.value = "";
    editor.disabled = true;
    $("#editor-title").textContent = t("untitled");
    $("#editor-path").textContent = "";
    renderOutline(null);
    renderCitations(null);
    renderProblems(null);
    updateAuthoringMode(null);
    return;
  }
  editor.disabled = model.readOnly;
  updateAuthoringMode(model);
  if (editor.value !== model.content) editor.value = model.content;
  $("#editor-title").textContent = model.title;
  $("#editor-path").textContent = model.path || t("untitled");
  setSaveState(documentDirty(model) ? "dirty" : "saved");
  updateLineGutter();
  updateEditorMetrics();
  renderOutline(isMarkdownModel(model) ? model : null);
  if (isMarkdownModel(model)) loadFrontMatterForm(model);
  renderCitations(isMarkdownModel(model) ? model : null);
  renderProblems(model);
  renderPreview(model);
}

/**
 * Let the webview read images from a document's own directory.
 *
 * The asset scope starts empty; this widens it by exactly one directory, and
 * only for a document the user actually opened.
 */
async function allowDocumentImages(model) {
  if (!model?.path) return;
  try {
    await invoke("allow_document_images", { path: model.path });
  } catch {
    // Images stay as Markdown text; nothing else about the document changes.
  }
}

function activateDocument(id) {
  const model = state.documents.find((document) => document.id === id);
  if (!model) return;
  state.activeDocumentId = id;
  void allowDocumentImages(model);
  state.validationSequence += 1;
  state.assetSequence += 1;
  state.bibliographySequence += 1;
  persistSession();
  renderWorkspace();
  currentEditor().focus();
  schedulePreview(80);
  if (model.path) refreshAssets();
}

function createUntitledDocument() {
  const model = createDocument({ content: "---\ntitle: \"\"\nlang: auto\n---\n\n# New document\n\n" });
  state.documents.push(model);
  state.activeDocumentId = model.id;
  showView("workspace");
  renderWorkspace();
  scheduleRecovery();
  schedulePreview(120);
  currentEditor().focus();
}

async function openAuthoringPaths(paths) {
  const values = [...new Set((Array.isArray(paths) ? paths : [paths]).filter(Boolean))];
  if (!values.length) return;
  showView("workspace");
  for (const path of values) {
    const existing = findDocumentByPath(state.documents, path);
    if (existing) {
      state.activeDocumentId = existing.id;
      continue;
    }
    try {
      const key = pathKey(path) || String(path);
      let request = state.documentOpenRequests.get(key);
      if (!request) {
        const readStandalone = isMarkdownPath(path) ? readDocument : readTextDocument;
        request = readStandalone(path).finally(() => state.documentOpenRequests.delete(key));
        state.documentOpenRequests.set(key, request);
      }
      const result = await request;
      const duplicate = findDocumentByPath(state.documents, result.path);
      const model = duplicate || createDocument({
        path: result.path,
        content: result.content,
        revision: result.revision,
        readOnly: result.read_only,
        kind: result.kind || (isMarkdownPath(result.path) ? "markdown" : "text"),
      });
      if (!duplicate) state.documents.push(model);
      state.activeDocumentId = model.id;
      saveRecent(model.path);
      const recovery = recoveryForPath(model.path);
      if (recovery && recovery.content !== model.content) showRecovery(model, recovery);
    } catch (error) {
      toast(errorText(error), "error");
    }
  }
  persistSession();
  renderWorkspace();
  schedulePreview(120);
  refreshAssets();
}

async function chooseAuthoringFiles() {
  try {
    const paths = await invoke("pick_markdown_files");
    await openAuthoringPaths(paths || []);
  } catch (error) {
    toast(errorText(error), "error");
  }
}

async function chooseProjectDirectory() {
  try {
    const path = await invoke("pick_project_directory");
    if (!path) return;
    await loadProject(path);
  } catch (error) {
    toast(errorText(error), "error");
  }
}

async function loadProject(path, { announce = true, openFirstChapter = true } = {}) {
  const handoff = pathKey(path) !== pathKey(state.project?.path)
    ? invalidateBookTaskForProjectChange()
    : Promise.resolve(true);
  const sequence = ++state.projectRequestSequence;
  await cancelActiveProjectSearch({ announce: false });
  await handoff;
  if (sequence !== state.projectRequestSequence) return null;
  const payload = await openProject(path);
  if (sequence !== state.projectRequestSequence) return null;
  applyProjectPayload(payload);
  state.bibliographyEntries = [];
  showView("workspace");
  activateSidebar("project");
  if (announce) toast(t("projectOpened"), "success");
  const firstChapter = payload.book?.chapters?.[0]?.path;
  if (openFirstChapter && firstChapter && !activeDocument()) {
    await openProjectRelativeFile(firstChapter);
  }
  return payload;
}

async function refreshActiveProject() {
  if (!state.project?.path) {
    await chooseProjectDirectory();
    return;
  }
  try {
    const projectPath = state.project.path;
    const sequence = ++state.projectRequestSequence;
    await cancelActiveProjectSearch({ announce: false });
    const payload = await refreshProject(projectPath);
    if (sequence !== state.projectRequestSequence || state.project?.path !== projectPath) return;
    applyProjectPayload(payload);
    toast(t("projectRefreshed"), "success");
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function renderProjectWorkspace() {
  const empty = $("#project-empty");
  const tools = $("#project-tools");
  const list = $("#project-file-tree");
  if (!empty || !tools || !list) return;
  const project = state.project;
  empty.classList.toggle("hidden", Boolean(project));
  tools.classList.toggle("hidden", !project);
  list.replaceChildren();
  if (!project) {
    $("#project-search-results")?.replaceChildren();
    return;
  }
  $("#project-name").textContent = project.name || t("projectWorkspace");
  $("#project-path").textContent = project.path || "";
  const files = Array.isArray(project.files) ? project.files : [];
  for (const file of files) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tool-item";
    button.dataset.kind = file.kind || "text";
    button.innerHTML = `<span></span>`;
    button.querySelector("span").textContent = file.chapter_title
      ? `${file.chapter_title} — ${file.path}`
      : file.path;
    if (["markdown", "text", "config", "toml", "bibliography", "json"].includes(file.kind)) {
      button.addEventListener("click", () => openProjectRelativeFile(file.path));
    } else {
      button.disabled = true;
    }
    list.append(button);
  }
}

async function openProjectRelativeFile(relativePath, { line = null, column = 1 } = {}) {
  const projectPath = state.project?.path;
  const projectGeneration = state.projectGeneration;
  if (!projectPath) return;
  try {
    const requestKey = `${projectGeneration}:${relativePath}`;
    let request = state.projectFileRequests.get(requestKey);
    if (!request) {
      request = readProjectFile(projectPath, relativePath)
        .finally(() => state.projectFileRequests.delete(requestKey));
      state.projectFileRequests.set(requestKey, request);
    }
    const result = await request;
    if (state.project?.path !== projectPath || state.projectGeneration !== projectGeneration) return;
    const existing = findDocumentByPath(state.documents, result.absolute_path);
    let model = existing;
    const file = state.project.files?.find((item) => item.path === result.path || item.path === relativePath);
    const kind = result.kind || file?.kind || "text";
    if (!model) {
      model = createDocument({
        path: result.absolute_path,
        content: result.content,
        revision: result.revision,
        readOnly: result.read_only,
        kind,
      });
      state.documents.push(model);
    } else if (result.content !== model.savedContent) {
      if (documentDirty(model)) {
        state.activeDocumentId = model.id;
        renderWorkspace();
        toast(t("projectFileConflict"), "error");
        return;
      }
      updateDocumentContent(model, result.content);
      markDocumentSaved(model, {
        path: result.absolute_path,
        revision: result.revision,
        read_only: result.read_only,
      }, result.content);
    }
    model.kind = kind;
    model.projectPath = projectPath;
    model.projectRelativePath = result.path;
    model.projectSha256 = result.sha256;
    state.activeDocumentId = model.id;
    showView("workspace");
    renderWorkspace();
    persistSession();
    schedulePreview(80);
    if (line) queueMicrotask(() => goToLine(line, column));
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function renderProjectSearchResults(result) {
  const list = $("#project-search-results");
  list.replaceChildren();
  const matches = Array.isArray(result?.matches) ? result.matches : [];
  if (!matches.length) {
    list.innerHTML = `<div class="tool-empty">${t("noSearchResults")}</div>`;
    return;
  }
  for (const match of matches) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tool-item";
    button.innerHTML = `<span class="match-location"></span><span class="match-preview"></span>`;
    button.querySelector(".match-location").textContent = `${match.path}:${match.line}:${match.column}`;
    button.querySelector(".match-preview").textContent = match.preview || "";
    button.addEventListener("click", () =>
      openProjectRelativeFile(match.path, { line: match.line, column: match.column })
    );
    list.append(button);
  }
  if (result?.truncated) {
    const notice = document.createElement("div");
    notice.className = "tool-empty search-limit-notice";
    notice.textContent = t("searchResultsLimited");
    list.append(notice);
  }
}

function resetProjectSearchButton() {
  const button = $("#run-project-search");
  if (!button) return;
  button.removeAttribute("aria-busy");
  button.dataset.state = "idle";
  button.textContent = t("find");
}

async function cancelActiveProjectSearch({ announce = true } = {}) {
  const requestId = state.activeProjectSearchRequestId;
  if (!requestId) return false;
  state.activeProjectSearchRequestId = null;
  state.projectSearchSequence += 1;
  resetProjectSearchButton();
  try {
    await cancelSidecarRequest(requestId);
  } catch {
    // A request that already completed no longer needs cancellation.
  }
  if (announce) toast(t("searchCancelled"), "info");
  return true;
}

async function runProjectSearch() {
  if (state.activeProjectSearchRequestId) {
    await cancelActiveProjectSearch();
    return;
  }

  const project = state.project;
  const query = $("#project-search-query").value.trim();
  if (!project?.path || !query) {
    renderProjectSearchResults({ matches: [] });
    return;
  }

  const sequence = ++state.projectSearchSequence;
  const task = startProjectSearch({
    projectPath: project.path,
    query,
    regex: $("#project-search-regex").checked,
    caseSensitive: $("#project-search-case").checked,
    maxResults: 200,
  });
  state.activeProjectSearchRequestId = task.requestId;
  const button = $("#run-project-search");
  button.dataset.state = "running";
  button.setAttribute("aria-busy", "true");
  button.textContent = t("cancelSearch");
  try {
    const result = await task.promise;
    if (sequence !== state.projectSearchSequence) return;
    renderProjectSearchResults(result);
  } catch (error) {
    if (sequence !== state.projectSearchSequence) return;
    const payload = errorPayload(error);
    const applicationCode = payload?.application_code || payload?.data?.application_code;
    if (applicationCode !== "MARDAS-JOB-CANCELLED") {
      toast(errorText(error), "error");
    }
  } finally {
    if (sequence === state.projectSearchSequence) {
      state.activeProjectSearchRequestId = null;
      resetProjectSearchButton();
    }
  }
}


function applyProjectPayload(payload) {
  const project = payload?.project || payload;
  if (!project?.path) return null;
  if (pathKey(project.path) !== pathKey(state.project?.path)) {
    invalidateBookTaskForProjectChange();
    state.bookOutputPath = null;
  }
  state.project = project;
  state.projectGeneration += 1;
  state.bibliographySequence += 1;
  state.assetSequence += 1;
  state.validationSequence += 1;
  state.previewSequence += 1;
  state.projectDiagnostics = Array.isArray(project.diagnostics) ? project.diagnostics : [];
  persistSession();
  renderProjectWorkspace();
  renderBookWorkspace();
  renderProblems(activeDocument());
  return project;
}

function folderNameFromTitle(value) {
  const normalized = String(value || "")
    .trim()
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return normalized || "mardas-book";
}

function openNewBookModal() {
  const titleInput = $("#book-project-title-input");
  const folderInput = $("#book-project-folder-input");
  titleInput.value = "";
  folderInput.value = "";
  folderInput.dataset.userEdited = "";
  $("#book-project-parent-input").value = "";
  $("#book-project-language").value = state.locale === "fa" ? "fa-IR" : "en-US";
  $("#book-project-direction").value = state.locale === "fa" ? "rtl" : "ltr";
  modalManager.open($("#book-project-modal"), {
    initialFocus: "#book-project-title-input",
    onClose: () => {
      $("#book-project-form").reset();
      folderInput.dataset.userEdited = "";
    },
  });
}

function closeNewBookModal() {
  modalManager.close($("#book-project-modal"));
}

async function chooseBookParent() {
  try {
    const path = await invoke("pick_project_directory");
    if (path) $("#book-project-parent-input").value = path;
  } catch (error) {
    toast(errorText(error), "error");
  }
}

async function submitNewBookProject(event) {
  event.preventDefault();
  const title = $("#book-project-title-input").value.trim();
  const folderName = $("#book-project-folder-input").value.trim() || folderNameFromTitle(title);
  const parentPath = $("#book-project-parent-input").value.trim();
  if (!title || !parentPath) {
    toast(t("chooseProjectLocation"), "warning");
    return;
  }
  const submit = event.submitter || $("#book-project-form button[type='submit']");
  submit.disabled = true;
  const handoff = invalidateBookTaskForProjectChange();
  try {
    await handoff;
    const project = await createBookProject({
      parentPath,
      folderName,
      title,
      language: $("#book-project-language").value,
      direction: $("#book-project-direction").value,
    });
    applyProjectPayload(project);
    closeNewBookModal();
    showView("workspace");
    activateSidebar("book");
    const first = project.book?.chapters?.[0]?.path;
    if (first) await openProjectRelativeFile(first);
    toast(t("bookCreated"), "success");
  } catch (error) {
    toast(errorText(error), "error");
  } finally {
    submit.disabled = false;
  }
}

function openChapterModal(mode, chapter = null) {
  state.chapterModalMode = mode;
  state.chapterModalPath = chapter?.path || null;
  const duplicate = mode === "duplicate";
  $("#chapter-modal-title").textContent = t(duplicate ? "duplicateChapter" : "addChapter");
  $("#chapter-modal-description").textContent = t("addChapterHelp");
  $("#chapter-title-input").value = duplicate
    ? `${chapter?.title || chapter?.path || t("chapterTitle")} ${state.locale === "fa" ? "کپی" : "Copy"}`
    : "";
  modalManager.open($("#chapter-modal"), {
    initialFocus: "#chapter-title-input",
    onClose: () => {
      state.chapterModalMode = null;
      state.chapterModalPath = null;
    },
  });
}

function closeChapterModal() {
  state.chapterModalMode = null;
  state.chapterModalPath = null;
  modalManager.close($("#chapter-modal"));
}

function bookProject() {
  return state.project?.book || null;
}

function setBookOperationStatus(message = "", { kind = "info", running = false } = {}) {
  const container = $("#book-operation-status");
  const text = $("#book-operation-message");
  const cancel = $("#book-cancel-operation");
  if (!container || !text || !cancel) return;
  container.classList.toggle("hidden", !message);
  container.dataset.kind = kind;
  text.textContent = message;
  cancel.classList.toggle("hidden", !running);
  syncBookOperationControls();
}

function syncBookOperationControls() {
  const locked = bookTaskBlocked(state);
  const tools = $("#book-tools");
  if (locked) tools?.setAttribute("aria-busy", "true");
  else tools?.removeAttribute("aria-busy");
  for (const control of $$(
    "#book-add-chapter, #book-validate, #book-preview, #book-export, #book-chapter-list button",
  )) {
    if (locked) {
      if (!("bookDisabledBeforeLock" in control.dataset)) {
        control.dataset.bookDisabledBeforeLock = String(control.disabled);
      }
      control.disabled = true;
    } else if ("bookDisabledBeforeLock" in control.dataset) {
      control.disabled = control.dataset.bookDisabledBeforeLock === "true";
      delete control.dataset.bookDisabledBeforeLock;
    }
  }
  $$("#book-chapter-list .book-chapter-row").forEach((row) => {
    row.draggable = !locked;
  });
}

async function cancelActiveBookOperation() {
  const requestId = state.activeBookRequestId;
  if (!requestId) return;
  try {
    await cancelSidecarRequest(requestId);
    setBookOperationStatus(t("searchCancelled"), { kind: "warning" });
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function invalidateBookTaskForProjectChange() {
  const requestId = state.activeBookRequestId;
  const completion = state.activeBookCompletion;
  state.bookRequestSequence += 1;
  state.activeBookRequestId = null;
  state.activeBookCompletion = null;
  setBookOperationStatus("");
  if (!requestId && !completion) {
    syncBookOperationControls();
    return state.bookCancellationHandoff || Promise.resolve(true);
  }
  const handoff = beginCancellationHandoff({
    completion,
    cancel: requestId ? () => cancelSidecarRequest(requestId) : null,
  });
  let trackedHandoff;
  trackedHandoff = handoff.finally(() => {
    if (state.bookCancellationHandoff === trackedHandoff) {
      state.bookCancellationHandoff = null;
    }
    syncBookOperationControls();
  });
  state.bookCancellationHandoff = trackedHandoff;
  syncBookOperationControls();
  return trackedHandoff;
}

function clearProjectState() {
  invalidateBookTaskForProjectChange();
  state.project = null;
  state.bookOutputPath = null;
  state.projectGeneration += 1;
  state.projectDiagnostics = [];
  state.bibliographyEntries = [];
  state.bibliographySequence += 1;
  state.assetSequence += 1;
  state.validationSequence += 1;
  state.previewSequence += 1;
}

async function runBookTask(startTask, {
  successMessage = "",
  onSuccess = null,
  showProblems = false,
} = {}) {
  const task = claimBookTask(state, startTask);
  if (!task) {
    toast(t("bookOperationAlreadyRunning"), "warning");
    syncBookOperationControls();
    return null;
  }
  const projectContext = currentProjectContext();
  const sequence = ++state.bookRequestSequence;
  const taskPromise = task.promise;
  setBookOperationStatus(t("bookOperationRunning"), { running: true });
  try {
    const result = await taskPromise;
    if (sequence !== state.bookRequestSequence || !projectContextIsCurrent(projectContext)) {
      return null;
    }
    if (result?.project?.path && pathKey(result.project.path) !== projectContext.projectIdentity) {
      return null;
    }
    if (result?.project) applyProjectPayload(result.project);
    if (typeof onSuccess === "function") await onSuccess(result);
    setBookOperationStatus(successMessage || t("bookValid"), { kind: "success" });
    if (successMessage) toast(successMessage, "success");
    if (showProblems) activateSidebar("problems");
    return result;
  } catch (error) {
    if (sequence !== state.bookRequestSequence || !projectContextIsCurrent(projectContext)) {
      return null;
    }
    const payload = errorPayload(error);
    const applicationCode =
      payload?.application_code
      || payload?.data?.application_code
      || payload?.code;
    if (applicationCode === "MARDAS-JOB-CANCELLED") {
      setBookOperationStatus(t("searchCancelled"), { kind: "warning" });
      return null;
    }
    const diagnostics =
      payload?.details?.diagnostics
      || payload?.data?.details?.diagnostics
      || payload?.diagnostics
      || [];
    if (diagnostics.length) {
      state.projectDiagnostics = diagnostics;
      renderProblems(activeDocument());
      activateSidebar("problems");
    }
    setBookOperationStatus(errorText(error), { kind: "error" });
    toast(errorText(error), "error");
    return null;
  } finally {
    if (sequence === state.bookRequestSequence) {
      state.activeBookRequestId = null;
      state.activeBookCompletion = null;
      $("#book-cancel-operation")?.classList.add("hidden");
    }
    syncBookOperationControls();
  }
}

async function submitChapterModal(event) {
  event.preventDefault();
  const project = state.project;
  const title = $("#chapter-title-input").value.trim();
  if (!project?.path || !project.config_sha256 || !title) return;
  const submit = event.submitter || $("#chapter-form button[type='submit']");
  submit.disabled = true;
  try {
    const result = state.chapterModalMode === "duplicate"
      ? await duplicateBookChapter({
          projectPath: project.path,
          relativePath: state.chapterModalPath,
          title,
          expectedConfigSha256: project.config_sha256,
        })
      : await addBookChapter({
          projectPath: project.path,
          title,
          expectedConfigSha256: project.config_sha256,
        });
    const mode = state.chapterModalMode;
    applyProjectPayload(result);
    closeChapterModal();
    const created = result.created_chapter?.path;
    if (created) await openProjectRelativeFile(created);
    toast(t(mode === "duplicate" ? "chapterDuplicated" : "chapterAdded"), "success");
  } catch (error) {
    toast(errorText(error), "error");
  } finally {
    submit.disabled = false;
  }
}

async function saveBookOrder(orderedPaths) {
  const project = state.project;
  if (!project?.path || !project.config_sha256) return;
  try {
    const result = await reorderBookChapters({
      projectPath: project.path,
      orderedPaths,
      expectedConfigSha256: project.config_sha256,
    });
    applyProjectPayload(result);
    toast(t("chapterOrderSaved"), "success");
  } catch (error) {
    toast(errorText(error), "error");
  }
}

async function moveBookChapter(path, delta) {
  const chapters = [...(bookProject()?.chapters || [])];
  const index = chapters.findIndex((chapter) => chapter.path === path);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= chapters.length) return;
  const [chapter] = chapters.splice(index, 1);
  chapters.splice(target, 0, chapter);
  await saveBookOrder(chapters.map((item) => item.path));
}

async function removeChapterFromBook(chapter) {
  const project = state.project;
  if (!project?.path || !project.config_sha256) return;
  if (!globalThis.confirm(t("confirmRemoveChapter"))) return;
  try {
    const result = await removeBookChapter({
      projectPath: project.path,
      relativePath: chapter.path,
      expectedConfigSha256: project.config_sha256,
    });
    applyProjectPayload(result);
    toast(t("chapterRemoved"), "success");
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function bookChapterRow(chapter, index, chapters) {
  const row = document.createElement("div");
  const activeRelativePath = activeDocument()?.projectRelativePath || null;
  const active = activeRelativePath === chapter.path;
  row.className = `book-chapter-row${active ? " active" : ""}`;
  row.draggable = true;
  row.dataset.path = chapter.path;
  row.innerHTML = `
    <span class="book-chapter-handle" aria-hidden="true">⋮⋮</span>
    <button class="book-chapter-main" type="button"><strong></strong><small></small></button>
    <span class="book-chapter-actions">
      <button type="button" data-action="up">↑</button>
      <button type="button" data-action="down">↓</button>
      <button type="button" data-action="duplicate">⧉</button>
      <button class="danger" type="button" data-action="remove">×</button>
    </span>`;
  const chapterLabel = `${index + 1}. ${chapter.title || chapter.path}`;
  row.querySelector("strong").textContent = chapterLabel;
  row.querySelector("small").textContent = chapter.path;
  const main = row.querySelector(".book-chapter-main");
  main.setAttribute("aria-label", `${t("openBookChapter")}: ${chapterLabel}`);
  if (active) main.setAttribute("aria-current", "page");
  main.addEventListener("click", () => openProjectRelativeFile(chapter.path));
  const actions = {
    up: [t("moveChapterUp"), () => moveBookChapter(chapter.path, -1)],
    down: [t("moveChapterDown"), () => moveBookChapter(chapter.path, 1)],
    duplicate: [t("duplicateChapter"), () => openChapterModal("duplicate", chapter)],
    remove: [t("removeFromBook"), () => removeChapterFromBook(chapter)],
  };
  for (const [action, [label, handler]] of Object.entries(actions)) {
    const button = row.querySelector(`[data-action="${action}"]`);
    button.title = label;
    button.setAttribute("aria-label", `${label}: ${chapterLabel}`);
    button.addEventListener("click", handler);
  }
  row.querySelector('[data-action="up"]').disabled = index === 0;
  row.querySelector('[data-action="down"]').disabled = index === chapters.length - 1;
  row.addEventListener("dragstart", (event) => {
    row.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", chapter.path);
  });
  row.addEventListener("dragend", () => row.classList.remove("dragging"));
  row.addEventListener("dragover", (event) => {
    event.preventDefault();
    row.classList.add("drag-over");
  });
  row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
  row.addEventListener("drop", (event) => {
    event.preventDefault();
    row.classList.remove("drag-over");
    const sourcePath = event.dataTransfer.getData("text/plain");
    if (!sourcePath || sourcePath === chapter.path) return;
    const paths = chapters.map((item) => item.path);
    const sourceIndex = paths.indexOf(sourcePath);
    const targetIndex = paths.indexOf(chapter.path);
    if (sourceIndex < 0 || targetIndex < 0) return;
    paths.splice(sourceIndex, 1);
    paths.splice(targetIndex, 0, sourcePath);
    saveBookOrder(paths);
  });
  return row;
}

function renderBookOutputResult() {
  const container = $("#book-output-result");
  const path = state.bookOutputPath;
  if (!container) return;
  container.classList.toggle("hidden", !path);
  if (!path) return;
  $("#book-output-result-name").textContent = basename(path);
  $("#book-output-result-path").textContent = path;
}

async function openBookOutput(reveal = false) {
  if (!state.bookOutputPath) return;
  try {
    await invoke(reveal ? "reveal_path" : "open_path", { path: state.bookOutputPath });
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function renderBookWorkspace() {
  const book = bookProject();
  const empty = $("#book-empty");
  const tools = $("#book-tools");
  const list = $("#book-chapter-list");
  if (!empty || !tools || !list) return;
  const enabled = Boolean(book);
  empty.classList.toggle("hidden", enabled);
  tools.classList.toggle("hidden", !enabled);
  $("#book-chapter-count").textContent = String(book?.chapter_count || 0);
  list.replaceChildren();
  if (!book) {
    syncBookOperationControls();
    return;
  }
  $("#book-project-title").textContent = book.title || state.project.name || t("bookProject");
  $("#book-output-path").textContent = book.output || "dist/book.pdf";
  const chapters = Array.isArray(book.chapters) ? book.chapters : [];
  const activeRelativePath = activeDocument()?.projectRelativePath || null;
  const activeIndex = chapters.findIndex((chapter) => chapter.path === activeRelativePath);
  $("#book-summary-chapters").textContent = String(chapters.length);
  $("#book-current-chapter").textContent = activeIndex >= 0 ? `${activeIndex + 1}/${chapters.length}` : "—";
  list.replaceChildren(...chapters.map((chapter, index) => bookChapterRow(chapter, index, chapters)));
  renderBookOutputResult();
  syncBookOperationControls();
}

async function validateActiveBook() {
  if (!state.project?.path || !bookProject()) return;
  await runBookTask(() => startBookValidation(state.project.path), {
    successMessage: t("bookValid"),
    showProblems: true,
  });
}

function renderFullBookPreview(html) {
  const parsed = new DOMParser().parseFromString(String(html || ""), "text/html");
  const container = $("#preview-document");
  container.replaceChildren();
  // Full renderer styles target html/body and must never escape into the desktop
  // shell. The authoring preview uses the app's isolated preview stylesheet.
  container.append(safePreviewHtml(parsed.body.innerHTML));
  $("#preview-detail").textContent = t("fullBookPreview");
  document.body.classList.add("book-preview-mode");
}

async function previewActiveBook() {
  if (!state.project?.path || !bookProject()) return;
  await runBookTask(() => startBookPreview(state.project.path), {
    successMessage: t("bookPreviewReady"),
    onSuccess: (result) => renderFullBookPreview(result.html),
  });
}

async function exportActiveBook() {
  const project = state.project;
  const book = bookProject();
  if (!project?.path || !book) return;
  let outputPath;
  try {
    outputPath = await invoke("pick_pdf_output", {
      suggested_path: `${project.path}/${book.output || "dist/book.pdf"}`,
    });
  } catch (error) {
    toast(errorText(error), "error");
    return;
  }
  if (!outputPath) return;
  await runBookTask(() => startBookExport({
    projectPath: project.path,
    outputPath,
  }), {
    successMessage: t("bookExported"),
    onSuccess: (result) => {
      state.outputResult = result;
      state.bookOutputPath = result?.output_path || outputPath;
      renderBookOutputResult();
    },
  });
}

function bibliographyEntryAuthors(entry) {
  const authors = Array.isArray(entry?.authors) ? entry.authors : [];
  return authors.map((author) => author.display || [author.family, author.given].filter(Boolean).join(", ")).filter(Boolean).join("; ");
}

function renderBibliographyEntries(entries, usedKeys = []) {
  state.bibliographyEntries = Array.isArray(entries) ? entries : [];
  const list = $("#citation-list");
  list.replaceChildren();
  $("#citation-count").textContent = String(state.bibliographyEntries.length);
  if (!state.bibliographyEntries.length) {
    list.innerHTML = `<div class="tool-empty">${t(state.project ? "noBibliography" : "noCitations")}</div>`;
    return;
  }
  for (const entry of state.bibliographyEntries) {
    const key = entry.key || entry.id;
    if (!key) continue;
    const cited = usedKeys.includes(key);
    const row = document.createElement("div");
    row.className = "tool-item citation-entry";
    row.dataset.cited = String(cited);
    row.innerHTML = `<span class="citation-key"></span><span class="citation-body"><strong></strong><small></small></span><span class="citation-state"></span><button class="citation-insert" type="button"></button>`;
    row.querySelector(".citation-key").textContent = `@${key}`;
    row.querySelector("strong").textContent = entry.title || key;
    row.querySelector("small").textContent = [bibliographyEntryAuthors(entry), entry.year].filter(Boolean).join(" · ");
    row.querySelector(".citation-state").textContent = t(cited ? "cited" : "uncited");
    const insert = row.querySelector(".citation-insert");
    insert.textContent = t("insert");
    insert.title = t("insertCitation");
    insert.addEventListener("click", () => insertAtCursor(`[@${key}]`));
    list.append(row);
  }
}

async function refreshBibliography() {
  const model = activeDocument();
  const used = extractCitationKeys(model?.content || "");
  if (!state.project?.path || model?.projectPath !== state.project.path) {
    renderCitations(model);
    return;
  }
  const sequence = ++state.bibliographySequence;
  const context = requestContext(model);
  const projectPath = state.project.path;
  try {
    const result = await bibliographyIndex({
      projectPath,
      query: $("#citation-search").value.trim(),
      citedKeys: used,
      maxResults: 500,
    });
    if (sequence !== state.bibliographySequence || !contextIsCurrent(context)) return;
    renderBibliographyEntries(result.entries, used);
    if (model) {
      model.bibliographyDiagnostics = Array.isArray(result.diagnostics)
        ? result.diagnostics
        : [];
      renderProblems(model);
    }
  } catch (error) {
    if (sequence !== state.bibliographySequence || !contextIsCurrent(context)) return;
    toast(errorText(error), "error");
  }
}

function showRecovery(model, recovery) {
  const item = { model, recovery };
  if (state.pendingRecovery) {
    state.recoveryQueue.push(item);
    return;
  }
  state.pendingRecovery = item;
  $("#recovery-message").textContent = `${t("recoveryMessage")} ${new Date(recovery.updatedAt).toLocaleString()}`;
  modalManager.open($("#recovery-modal"), {
    initialFocus: "#restore-recovery",
    escape: false,
  });
}

function resolveRecovery(restore) {
  const pending = state.pendingRecovery;
  if (!pending) return;
  if (restore) updateDocumentContent(pending.model, pending.recovery.content);
  else removeRecovery(pending.recovery.key);
  state.pendingRecovery = null;
  modalManager.close($("#recovery-modal"));
  activateDocument(pending.model.id);
  const next = state.recoveryQueue.shift();
  if (next) showRecovery(next.model, next.recovery);
}

async function saveActiveDocument({ saveAs = false, force = false } = {}) {
  const model = activeDocument();
  if (!model) return false;
  return saveCoordinator.save(
    model,
    () => persistDocumentModel(model, { saveAs, force }),
    { alwaysRun: saveAs },
  );
}

async function persistDocumentModel(model, { saveAs = false, force = false } = {}) {
  if (!state.documents.includes(model)) return false;
  if (model.readOnly && !saveAs) {
    toast(t("readOnlyDocument"), "error");
    return false;
  }
  let path = model.path;
  if (!path || saveAs) {
    try {
      const picker = isMarkdownModel(model) ? "pick_markdown_output" : "pick_text_output";
      path = await invoke(picker, {
        suggested_path: model.path || `${model.title.replace(/\s+/g, "-")}.md`,
      });
    } catch (error) {
      if (activeDocument()?.id === model.id) toast(errorText(error), "error");
      return false;
    }
    if (!path) return false;
  }
  const collision = findSavePathCollision(state.documents, model, path);
  if (collision) {
    activateDocument(collision.id);
    toast(t("saveAsPathAlreadyOpen"), "error");
    return false;
  }
  if (activeDocument()?.id === model.id) setSaveState("saving");
  const contentSnapshot = model.content;
  const isProjectSave = !saveAs && Boolean(model.projectPath && model.projectRelativePath);
  try {
    const previousRecoveryKey = recoveryKey(model);
    let result;
    if (isProjectSave) {
      result = await saveProjectFile({
        projectPath: model.projectPath,
        relativePath: model.projectRelativePath,
        content: contentSnapshot,
        expectedSha256: model.projectSha256,
      });
      model.projectSha256 = result.sha256;
      markDocumentSaved(model, {
        path: result.absolute_path || model.path,
        revision: result.revision,
        read_only: result.read_only,
      }, contentSnapshot);
    } else {
      const saveStandalone = isMarkdownModel(model) ? saveDocument : saveTextDocument;
      result = await saveStandalone({
        path,
        content: contentSnapshot,
        expectedRevision: pathKey(path) === pathKey(model.path) ? model.revision : null,
        force,
      });
      markDocumentSaved(model, result, contentSnapshot);
      if (saveAs && model.projectPath) {
        delete model.projectPath;
        delete model.projectRelativePath;
        delete model.projectSha256;
      }
    }
    removeRecovery(previousRecoveryKey);
    if (documentDirty(model)) saveRecovery(model);
    else {
      removeRecovery(model);
      cancelRecoveryTimer(model);
    }
    saveRecent(model.path);
    persistSession();
    if (activeDocument()?.id === model.id) {
      renderWorkspace();
      toast(t("documentSaved"), "success");
    } else {
      renderDocumentTabs();
    }
    if (isProjectSave && model.projectRelativePath === "mardas.toml") {
      void refreshActiveProject();
    }
    return true;
  } catch (error) {
    const payload = errorPayload(error);
    const applicationCode = payload?.application_code || payload?.data?.application_code || payload?.code;
    const conflict = applicationCode === "MARDAS-DOCUMENT-CONFLICT"
      || applicationCode === "MARDAS-PROJECT-FILE-CHANGED"
      || applicationCode === "project_file_changed";
    if (conflict) {
      if (activeDocument()?.id === model.id) setSaveState("dirty");
      if (isProjectSave) {
        if (activeDocument()?.id === model.id) toast(t("projectFileConflict"), "error");
        return false;
      }
      const overwrite = globalThis.confirm(`${t("documentConflict")}\n\n${t("forceSave")}?`);
      if (overwrite) return persistDocumentModel(model, { saveAs: false, force: true });
      return false;
    }
    if (activeDocument()?.id === model.id) {
      setSaveState("dirty");
      toast(errorText(error), "error");
    }
    return false;
  }
}

function requestCloseDocument(id) {
  const model = state.documents.find((document) => document.id === id);
  if (!model) return;
  if (documentDirty(model) && !globalThis.confirm(`${model.title}: ${t("unsaved")}. ${t("close")}?`)) return;
  cancelRecoveryTimer(model);
  removeRecovery(model);
  const result = closeDocument(state.documents, id);
  state.documents = result.documents;
  state.activeDocumentId = result.nextId;
  persistSession();
  renderWorkspace();
  if (!state.documents.length) showView("start");
}

function onEditorInput() {
  const model = activeDocument();
  if (!model) return;
  updateDocumentContent(model, currentEditor().value);
  state.validationSequence += 1;
  state.bibliographySequence += 1;
  model.diagnostics = [];
  setSaveState("dirty");
  renderDocumentTabs();
  renderOutline(model);
  renderCitations(model);
  updateLineGutter();
  updateEditorMetrics();
  scheduleRecovery();
  schedulePreview();
}

function cancelRecoveryTimer(model) {
  if (!model?.id) return;
  const timer = state.recoveryTimers.get(model.id);
  if (timer !== undefined) clearTimeout(timer);
  state.recoveryTimers.delete(model.id);
}

function scheduleRecovery(model = activeDocument()) {
  if (!model) return;
  cancelRecoveryTimer(model);
  const timer = setTimeout(() => {
    state.recoveryTimers.delete(model.id);
    if (!state.documents.includes(model) || !documentDirty(model)) return;
    const result = saveRecovery(model);
    if (activeDocument()?.id === model.id) {
      $("#recovery-status").textContent = result.ok ? t("recoverySaved") : result.reason === "too_large" ? t("recoveryTooLarge") : "";
      setTimeout(() => {
        if ($("#recovery-status") && activeDocument()?.id === model.id) {
          $("#recovery-status").textContent = "";
        }
      }, 2500);
    }
  }, 700);
  state.recoveryTimers.set(model.id, timer);
}

function schedulePreview(delay = 650) {
  const sequence = ++state.previewSequence;
  clearTimeout(state.previewTimer);
  const model = activeDocument();
  if (!model || !isMarkdownModel(model) || !model.content.trim()) {
    if (model) model.preview = null;
    renderPreview(model);
    $("#preview-loading")?.classList.add("hidden");
    return;
  }
  if (!$("#auto-preview")?.checked) return;
  state.previewTimer = setTimeout(() => refreshPreview(sequence), delay);
}

function previewOptions() {
  // The engine already applies project configuration and the buffer's front matter.
  // Keeping request overrides sparse preserves that documented precedence.
  return {};
}

function safePreviewHtml(value) {
  const template = document.createElement("template");
  template.innerHTML = String(value || "");
  template.content
    .querySelectorAll("script,style,iframe,object,embed,meta,base,link,form,button,select,option,textarea")
    .forEach((element) => element.remove());
  const idMap = new Map();
  template.content.querySelectorAll("[id]").forEach((element) => {
    const original = element.id;
    const prefixed = `preview-${original}`;
    idMap.set(original, prefixed);
    element.dataset.previewSourceId = original;
    element.id = prefixed;
  });
  template.content.querySelectorAll("*").forEach((element) => {
    const reservedClasses = new Set(["active", "hidden", "modal", "toast", "view", "sidebar-panel", "source-active"]);
    for (const className of [...element.classList]) {
      if (reservedClasses.has(className)) element.classList.remove(className);
    }
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (
        name.startsWith("on")
        || [
          "action",
          "autofocus",
          "background",
          "contenteditable",
          "data",
          "download",
          "draggable",
          "formaction",
          "ping",
          "poster",
          "srcdoc",
          "srcset",
          "style",
          "target",
          "xlink:href",
        ].includes(name)
      ) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (name === "href") {
        if (attribute.value.startsWith("#")) {
          const target = attribute.value.slice(1);
          element.setAttribute("href", `#${idMap.get(target) || `preview-${target}`}`);
        } else {
          element.removeAttribute("href");
          element.setAttribute("aria-disabled", "true");
        }
      }
      if (name === "src" && !/^\s*data:image\//i.test(attribute.value)) {
        element.removeAttribute(attribute.name);
      }
      if (["for", "aria-labelledby", "aria-describedby"].includes(name)) {
        const rewritten = attribute.value
          .split(/\s+/)
          .map((id) => idMap.get(id) || `preview-${id}`)
          .join(" ");
        element.setAttribute(attribute.name, rewritten);
      }
      // Prefixing ids also has to prefix what points at them. A Mermaid
      // arrowhead is a `<marker id=…>` referenced by `marker-end="url(#…)"`,
      // so rewriting one without the other left every diagram without arrows.
      if (attribute.value.includes("url(#")) {
        element.setAttribute(
          attribute.name,
          attribute.value.replace(
            /url\(#([^)"']+)\)/g,
            (whole, id) => `url(#${idMap.get(id) || `preview-${id}`})`,
          ),
        );
      }
    }
    if (element instanceof HTMLInputElement) {
      if (element.type !== "checkbox") {
        element.remove();
      } else {
        element.disabled = true;
        element.tabIndex = -1;
      }
    }
  });
  return template.content;
}

function renderPreviewMessage(title, detail = "") {
  document.body.classList.remove("book-preview-mode");
  const container = $("#preview-document");
  const message = document.createElement("div");
  message.className = "empty-preview";
  const heading = document.createElement("strong");
  heading.textContent = String(title || "");
  message.append(heading);
  if (detail) {
    const description = document.createElement("small");
    description.textContent = String(detail);
    message.append(description);
  }
  container.replaceChildren(message);
}

function previewSourceEntries(model = activeDocument()) {
  const entries = Array.isArray(model?.preview?.source_map)
    ? model.preview.source_map
    : Array.isArray(model?.preview?.document?.source_map)
      ? model.preview.document.source_map
      : [];
  return entries
    .map((entry) => ({
      id: String(entry.id || ""),
      line: Number(entry.line) || 0,
      level: Number(entry.level) || 0,
      title: String(entry.title || ""),
    }))
    .filter((entry) => entry.id && entry.line > 0)
    .sort((left, right) => left.line - right.line);
}

function syncPreviewToEditorLine(line, { center = false } = {}) {
  const container = $("#preview-document");
  const entries = previewSourceEntries();
  if (!container || !entries.length) return;
  let active = entries[0];
  for (const entry of entries) {
    if (entry.line > line) break;
    active = entry;
  }
  container.querySelectorAll(".source-active").forEach((element) => element.classList.remove("source-active"));
  const target = container.querySelector(`#${CSS.escape(`preview-${active.id}`)}`)
    || container.querySelector(`[data-source-line="${active.line}"]`);
  if (!target) return;
  target.classList.add("source-active");
  if (center && !state.previewSyncing) {
    state.previewSyncing = true;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    setTimeout(() => { state.previewSyncing = false; }, 180);
  }
}

function syncPreviewFromEditorScroll(scrollTop) {
  const editorElement = editorAdapter?.element || $("#markdown-editor");
  if (!editorElement || state.previewSyncing) return;
  const lineHeight = Number.parseFloat(getComputedStyle(editorElement).lineHeight) || 24;
  const visibleLine = Math.max(1, Math.floor((Number(scrollTop) || 0) / lineHeight) + 1);
  syncPreviewToEditorLine(visibleLine);
}

function renderPreview(model) {
  document.body.classList.remove("book-preview-mode");
  const container = $("#preview-document");
  if (model && !isMarkdownModel(model)) {
    renderPreviewMessage(t("plainTextMode"));
    return;
  }
  if (!model?.preview) {
    renderPreviewMessage(t("previewEmpty"));
    return;
  }
  container.replaceChildren();
  if (model.preview.pygments_css) {
    const style = document.createElement("style");
    style.textContent = model.preview.pygments_css;
    container.append(style);
  }
  container.append(safePreviewHtml(`${model.preview.body_html || ""}${model.preview.reference_lists_html || ""}${model.preview.bibliography_html || ""}`));
  const sourceEntries = previewSourceEntries(model);
  const byId = new Map(sourceEntries.map((entry) => [entry.id, entry]));
  container.querySelectorAll("h1,h2,h3,h4,h5,h6").forEach((heading) => {
    const sourceId = heading.dataset.previewSourceId || heading.id.replace(/^preview-/, "");
    const sourceLine = Number(heading.dataset.sourceLine) || byId.get(sourceId)?.line || 0;
    if (!sourceLine) return;
    heading.dataset.sourceLine = String(sourceLine);
    heading.classList.add("preview-source-link");
    heading.title = `Line ${sourceLine}`;
    heading.tabIndex = 0;
    heading.setAttribute("role", "button");
    heading.addEventListener("click", () => goToLine(sourceLine));
    heading.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      goToLine(sourceLine);
    });
  });
  const cursor = currentEditor();
  const position = editorAdapter?.lineAtOffset(cursor.selectionStart)
    || textMetrics(cursor.value, cursor.selectionStart);
  syncPreviewToEditorLine(position.line);
}

async function refreshPreview(scheduledSequence = null) {
  const sequence = scheduledSequence ?? ++state.previewSequence;
  if (sequence !== state.previewSequence) return;
  const model = activeDocument();
  if (!model || !isMarkdownModel(model) || !model.content.trim()) {
    if (model) model.preview = null;
    renderPreview(model);
    return;
  }
  const context = requestContext(model);
  $("#preview-loading").classList.remove("hidden");
  try {
    const result = await previewDocumentText({ path: model.path, content: model.content, options: previewOptions() });
    if (sequence !== state.previewSequence || !contextIsCurrent(context)) return;
    model.preview = result;
    model.diagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
    renderPreview(model);
    renderCitations(model);
    renderProblems(model);
    $("#preview-detail").textContent = result.title || t("previewHelp");
  } catch (error) {
    if (sequence !== state.previewSequence || !contextIsCurrent(context)) return;
    const payload = errorPayload(error);
    model.diagnostics = payload?.details?.diagnostics || payload?.diagnostics || [];
    renderProblems(model);
    renderPreviewMessage(t("previewFailed"), errorText(error));
  } finally {
    if (sequence === state.previewSequence) $("#preview-loading").classList.add("hidden");
  }
}

async function validateActiveDocument() {
  const model = activeDocument();
  if (!model || !isMarkdownModel(model)) return;
  const sequence = ++state.validationSequence;
  const context = requestContext(model);
  try {
    const result = await validateDocumentText({ path: model.path, content: model.content, options: previewOptions() });
    if (sequence !== state.validationSequence || !contextIsCurrent(context)) return;
    model.diagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
    renderProblems(model);
    activateSidebar("problems");
    toast(result.ok ? t("validMessage") : t("invalidMessage"), result.ok ? "success" : "error");
  } catch (error) {
    if (sequence !== state.validationSequence || !contextIsCurrent(context)) return;
    toast(errorText(error), "error");
  }
}

async function refreshAssets() {
  const model = activeDocument();
  if (!model?.path) {
    renderAssets([]);
    return;
  }
  const sequence = ++state.assetSequence;
  const context = requestContext(model);
  try {
    const result = await listDocumentAssets(model.path);
    if (sequence !== state.assetSequence || !contextIsCurrent(context, { requireContent: false })) return;
    renderAssets(Array.isArray(result.assets) ? result.assets : []);
  } catch (error) {
    if (sequence !== state.assetSequence || !contextIsCurrent(context, { requireContent: false })) return;
    renderAssets([]);
    toast(errorText(error), "error");
  }
}

async function importAsset() {
  const model = activeDocument();
  if (!model?.path || !isMarkdownModel(model)) {
    toast(t("saveBeforeAsset"), "error");
    return;
  }
  const context = requestContext(model);
  try {
    const source = await invoke("pick_document_asset");
    if (!source) return;
    if (!contextIsCurrent(context, { requireContent: false })) return;
    const asset = await importDocumentAsset(model.path, source);
    if (!contextIsCurrent(context, { requireContent: false })) return;
    toast(t("assetImported"), "success");
    insertAssetReference(asset, model);
    await refreshAssets();
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function insertAssetReference(asset, model = activeDocument()) {
  if (!model || activeDocument()?.id !== model.id || !isMarkdownModel(model)) return;
  const extension = String(asset.extension || asset.name?.slice(asset.name.lastIndexOf(".")) || "").toLowerCase();
  const path = asset.relative_path || asset.name;
  if ([".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif", ".bmp"].includes(extension)) {
    insertAtCursor(`![${asset.name || "Image"}](${path})`);
  } else if (extension === ".bib") {
    let content = upsertFrontMatter(model.content, "bibliography", [path]);
    content = upsertFrontMatter(content, "citations", true);
    applyEditorContent(content);
  }
}

function activateSidebar(name) {
  state.activeSidebar = name;
  $$("[data-sidebar]").forEach((button) => {
    const active = button.dataset.sidebar === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  $$("[data-panel]").forEach((panel) => {
    const active = panel.dataset.panel === name;
    panel.classList.toggle("active", active);
    panel.setAttribute("aria-hidden", String(!active));
  });
  if (name === "assets") refreshAssets();
  if (name === "project") renderProjectWorkspace();
  if (name === "citations") refreshBibliography();
}

function goToLine(line, column = 1) {
  const editor = currentEditor();
  if (editorAdapter) editorAdapter.goToLine(line, column);
  else {
    const lines = editor.value.split("\n");
    let offset = 0;
    for (let index = 0; index < Math.max(0, line - 1); index += 1) offset += lines[index].length + 1;
    offset += Math.max(0, column - 1);
    editor.focus();
    editor.setSelectionRange(offset, offset);
  }
  updateEditorMetrics();
  syncPreviewToEditorLine(Number(line) || 1, { center: true });
}

function updateFindMatches({ preserveIndex = false } = {}) {
  const editor = currentEditor();
  const query = $("#find-query").value;
  const matches = findLiteralMatches(editor.value, query);
  state.findMatches = matches;
  if (!preserveIndex || state.findIndex >= matches.length) state.findIndex = matches.length ? 0 : -1;
  $("#find-count").textContent = matches.length ? `${state.findIndex + 1}/${matches.length}` : "0/0";
  return matches;
}

function selectFindMatch(index) {
  const matches = state.findMatches;
  if (!matches.length) return;
  state.findIndex = (index + matches.length) % matches.length;
  const match = matches[state.findIndex];
  const editor = currentEditor();
  editor.focus();
  editor.setSelectionRange(match.start, match.end);
  // The professional editor scrolls the selection into view itself, and knows
  // where a wrapped line actually sits. Only the plain-textarea fallback has to
  // be scrolled by hand — and asking the adapter *object* for a computed style,
  // as this once did, threw before the count below was ever updated, which took
  // find-and-replace navigation down with it.
  if (editorAdapter?.kind !== "codemirror") {
    const element = editorAdapter?.element || $("#markdown-editor");
    const line = editor.value.slice(0, match.start).split("\n").length;
    const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight) || 24;
    editor.scrollTop = Math.max(0, (line - 4) * lineHeight);
  }
  $("#find-count").textContent = `${state.findIndex + 1}/${matches.length}`;
  updateEditorMetrics();
}

function openFind({ replace = false } = {}) {
  $("#find-bar").classList.remove("hidden");
  $("#replace-query").classList.toggle("hidden", !replace);
  $("#replace-one").classList.toggle("hidden", !replace);
  $("#replace-all").classList.toggle("hidden", !replace);
  const editor = currentEditor();
  const selected = editor.value.slice(editor.selectionStart, editor.selectionEnd);
  if (selected && !selected.includes("\n")) $("#find-query").value = selected;
  updateFindMatches();
  $("#find-query").focus();
  $("#find-query").select();
}

function closeFind() {
  $("#find-bar").classList.add("hidden");
  state.findMatches = [];
  state.findIndex = -1;
  currentEditor().focus();
}

function moveFind(direction) {
  if (!state.findMatches.length) updateFindMatches();
  if (state.findMatches.length) selectFindMatch(state.findIndex + direction);
}

function replaceCurrentMatch() {
  const editor = currentEditor();
  if (!state.findMatches.length) return;
  const match = state.findMatches[state.findIndex];
  const replacement = $("#replace-query").value;
  applyEditorResult(replaceSelection(editor.value, match.start, match.end, replacement));
  updateFindMatches();
  if (state.findMatches.length) selectFindMatch(Math.min(state.findIndex, state.findMatches.length - 1));
}

function replaceAllMatches() {
  const query = $("#find-query").value;
  if (!query) return;
  const replacement = $("#replace-query").value;
  const editor = currentEditor();
  editor.value = replaceAllLiteral(editor.value, query, replacement).text;
  editor.setSelectionRange(0, 0);
  onEditorInput();
  updateFindMatches();
}

function applyEditorResult(result) {
  const editor = currentEditor();
  editor.value = result.text;
  editor.focus();
  editor.setSelectionRange(result.start, result.end);
  onEditorInput();
}

function applyEditorContent(content) {
  const editor = currentEditor();
  const cursor = Math.min(editor.selectionStart, content.length);
  editor.value = content;
  editor.setSelectionRange(cursor, cursor);
  onEditorInput();
}

function insertAtCursor(value) {
  const editor = currentEditor();
  applyEditorResult(replaceSelection(editor.value, editor.selectionStart, editor.selectionEnd, value));
}

/**
 * Run a formatting command, wherever it was asked for.
 *
 * The professional editor owns the whole command vocabulary — toggling,
 * multi-line block edits, heading levels — and shares one undo history with
 * the keyboard. Only the plain-textarea fallback needs the string surgery
 * below, and it covers the subset that fallback can express.
 */
function editorCommand(command) {
  const model = activeDocument();
  if (!model || model.readOnly || !isMarkdownModel(model)) return;
  if (editorAdapter?.runCommand?.(command)) {
    onEditorInput();
    return;
  }
  const editor = currentEditor();
  let result;
  if (command === "bold") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "**", "**", "bold text");
  if (command === "italic") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "_", "_", "italic text");
  if (command === "link") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "[", "](https://)", "link text");
  if (command === "code") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "`", "`", "code");
  if (command === "heading") result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "## ");
  if (command === "citation") result = replaceSelection(editor.value, editor.selectionStart, editor.selectionEnd, "[@citation-key]", 2);
  if (command === "strike") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "~~", "~~", "struck text");
  if (command === "bullet-list") result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "- ");
  if (command === "ordered-list") result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "1. ");
  if (command === "task-list") result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "- [ ] ");
  if (command === "quote") result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "> ");
  if (command === "image") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "![", "](assets/image.png)", "alt text");
  if (command === "rule") result = replaceSelection(editor.value, editor.selectionStart, editor.selectionEnd, "\n---\n");
  if (command === "code-block") {
    result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "```\n", "\n```", "code");
  }
  if (command === "table") {
    // A minimal GitHub table the user can extend, rather than a dialog to fill in.
    result = replaceSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "\n| A | B |\n| --- | --- |\n|  |  |\n",
    );
  }
  if (result) applyEditorResult(result);
}

// ---------------------------------------------------------------------------
// Editor menus
// ---------------------------------------------------------------------------

/**
 * The heading chooser.
 *
 * A single "H2" button could only ever apply one level, so every other heading
 * had to be typed by hand. The menu shows each level at its own weight, because
 * the decision being made is about size, not about a number.
 */
function toggleHeadingMenu(force) {
  const menu = $("#heading-menu");
  const button = $("#heading-menu-button");
  if (!menu || !button) return;
  const open = force === undefined ? menu.classList.contains("hidden") : force;
  menu.classList.toggle("hidden", !open);
  button.setAttribute("aria-expanded", String(open));
  if (!open) return;
  const box = button.getBoundingClientRect();
  menu.style.top = `${box.bottom + 4}px`;
  menu.style.insetInlineStart = `${document.documentElement.dir === "rtl"
    ? window.innerWidth - box.right
    : box.left}px`;
  menu.querySelector("button")?.focus();
}

/** Plain text of the current selection, or the whole document. */
function selectionOrDocument() {
  const editor = currentEditor();
  const selected = editor.value.slice(editor.selectionStart, editor.selectionEnd);
  return selected || editor.value;
}

async function copyToClipboard(text, { html = null } = {}) {
  try {
    if (html && navigator.clipboard?.write && typeof ClipboardItem === "function") {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        }),
      ]);
      return true;
    }
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    toast(t("clipboardUnavailable"), "error");
    return false;
  }
}

/** Copy the rendered document as HTML, for pasting into a word processor. */
async function copyAsHtml() {
  const model = activeDocument();
  const html = model?.preview?.body_html;
  if (!html) {
    toast(t("previewEmpty"));
    return;
  }
  const plain = document.createElement("div");
  plain.append(safePreviewHtml(html));
  if (await copyToClipboard(plain.textContent || "", { html })) toast(t("copied"), "success");
}

async function pasteAsPlainText() {
  const model = activeDocument();
  if (!model || model.readOnly) return;
  try {
    const text = await navigator.clipboard.readText();
    if (text) insertAtCursor(text);
  } catch {
    toast(t("clipboardUnavailable"), "error");
  }
}

/**
 * The editor's own context menu.
 *
 * Right-clicking a document is expected to offer document actions — copy as
 * HTML, insert an image, export — rather than the webview's menu, which offers
 * "Reload" and "View source". Secondary and file-level actions live here so the
 * toolbar can stay short.
 */
function openEditorContextMenu(event) {
  closeEditorContextMenu();
  const model = activeDocument();
  const editable = Boolean(model) && !model.readOnly && isMarkdownModel(model);
  const hasSelection = currentEditor().selectionStart !== currentEditor().selectionEnd;

  const items = [
    { key: "copy", label: t("copy"), enabled: hasSelection, run: () => copyToClipboard(selectionOrDocument()) },
    { key: "copyHtml", label: t("copyAsHtml"), enabled: Boolean(model?.preview), run: copyAsHtml },
    { key: "copyPlain", label: t("copyAsPlainText"), enabled: true, run: () => copyToClipboard(selectionOrDocument()) },
    { key: "paste", label: t("pasteAsPlainText"), enabled: editable, run: pasteAsPlainText },
    { separator: true },
    { key: "image", label: t("insertImage"), enabled: editable, run: importAsset },
    { key: "citation", label: t("insertCitation"), enabled: editable, run: () => editorCommand("citation") },
    { key: "table", label: t("insertTable"), enabled: editable, run: () => editorCommand("table") },
    { separator: true },
    { key: "validate", label: t("checkDocument"), enabled: Boolean(model), run: validateActiveDocument },
    { key: "export", label: t("exportPdf"), enabled: Boolean(model), run: exportActiveDocument },
    { key: "reveal", label: t("showInFolder"), enabled: Boolean(model?.path), run: () => invoke("reveal_path", { path: model.path }).catch(() => {}) },
  ];

  const menu = $("#editor-context-menu");
  if (!menu) return;
  menu.replaceChildren();

  for (const item of items) {
    if (item.separator) {
      const rule = document.createElement("span");
      rule.className = "context-menu-separator";
      rule.setAttribute("role", "separator");
      menu.append(rule);
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "context-menu-item";
    button.setAttribute("role", "menuitem");
    button.textContent = item.label;
    button.disabled = !item.enabled;
    button.addEventListener("click", () => {
      closeEditorContextMenu();
      item.run();
    });
    menu.append(button);
  }
  menu.classList.remove("hidden");
  menu.setAttribute("aria-hidden", "false");

  // A menu that runs off the window is a menu with items nobody can reach.
  const box = menu.getBoundingClientRect();
  const left = Math.min(event.clientX, window.innerWidth - box.width - 8);
  const top = Math.min(event.clientY, window.innerHeight - box.height - 8);
  menu.style.left = `${Math.max(8, left)}px`;
  menu.style.top = `${Math.max(8, top)}px`;
  menu.querySelector("button:not([disabled])")?.focus();
}

function closeEditorContextMenu() {
  const menu = $("#editor-context-menu");
  if (!menu || menu.classList.contains("hidden")) return;
  menu.classList.add("hidden");
  menu.setAttribute("aria-hidden", "true");
  menu.replaceChildren();
}

function applyFrontMatter(event) {
  event.preventDefault();
  const model = activeDocument();
  if (!model || model.readOnly || !isMarkdownModel(model)) return;
  const form = event.currentTarget;
  let content = model.content;
  for (const key of ["title", "subtitle", "author", "lang", "dir"]) {
    content = upsertFrontMatter(content, key, form.elements.namedItem(key).value);
  }
  content = upsertFrontMatter(content, "toc", form.elements.namedItem("toc").checked);
  applyEditorContent(content);
  schedulePreview(80);
}

async function exportActiveDocument() {
  const model = activeDocument();
  if (!model || !isMarkdownModel(model)) return;
  if (!model.path || documentDirty(model)) {
    const saved = await saveActiveDocument();
    if (!saved) return;
  }
  openExportSource(model.path);
}

// ---------------------------------------------------------------------------
// Runtime lifecycle and event wiring
// ---------------------------------------------------------------------------
async function engineHealth() {
  const element = $("#engine-state");
  try {
    const health = await invoke("sidecar_request", { request_id: requestId("health"), method: "system.health", params: {} });
    element.dataset.state = "ready";
    element.querySelector("span").dataset.i18n = "engineReady";
    element.querySelector("span").textContent = t("engineReady");
    $("#runtime-detail").textContent = `${health.engine_version || ""} · ${health.runtime?.platform || t("localRuntime")}`;
  } catch (error) {
    element.dataset.state = "error";
    element.querySelector("span").dataset.i18n = "engineUnavailable";
    element.querySelector("span").textContent = t("engineUnavailable");
    $("#runtime-detail").textContent = t("sidecarUnavailableDetail");
    toast(errorText(error), "error");
  }
}

function bindEvents() {
  $("#home-button").addEventListener("click", () => showView("start"));
  $("#command-button").addEventListener("click", openCommandPalette);
  $("#help-button").addEventListener("click", openHelp);
  $("#settings-button").addEventListener("click", openSettings);
  $("#template-help").addEventListener("click", openHelp);
  for (const button of $$("[data-view-mode]")) {
    button.addEventListener("click", () => setViewMode(button.dataset.viewMode));
  }
  $("#reset-advanced").addEventListener("click", resetAdvancedOptions);
  $("#option-search").addEventListener("input", (event) => {
    optionSearchQuery = event.target.value;
    renderOptionRail();
    renderOptionPane();
  });
  $("#show-expert").addEventListener("change", (event) => {
    showExpertOptions = event.target.checked;
    // A hidden expert group must not stay selected, or the pane would be empty.
    const group = OPTION_GROUPS.find((item) => item.id === activeOptionGroup);
    if (group?.expert && !showExpertOptions) activeOptionGroup = OPTION_GROUPS[0].id;
    renderAdvancedOptions();
  });
  $("#option-rail").addEventListener("keydown", (event) => {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    const items = [...$("#option-rail").querySelectorAll(".option-rail-item")];
    const index = items.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    let next = index;
    if (event.key === "ArrowUp") next = (index - 1 + items.length) % items.length;
    if (event.key === "ArrowDown") next = (index + 1) % items.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = items.length - 1;
    items[next].click();
    items[next].focus();
  });
  $("#preview-zoom-in").addEventListener("click", () => exportPreviewDeck()?.zoomBy(1));
  $("#preview-zoom-out").addEventListener("click", () => exportPreviewDeck()?.zoomBy(-1));
  $("#preview-fit-width").addEventListener("click", () => exportPreviewDeck()?.setZoomMode("fit-width"));
  $("#preview-fit-page").addEventListener("click", () => exportPreviewDeck()?.setZoomMode("fit-page"));
  $("#preview-guides").addEventListener("click", () => exportPreviewDeck()?.toggleGuides());
  $("#preview-prev-page").addEventListener("click", () => movePreviewPage(-1));
  $("#preview-next-page").addEventListener("click", () => movePreviewPage(1));
  $("#workflow-quick").addEventListener("click", () => showView("export"));
  $("#workflow-open").addEventListener("click", chooseAuthoringFiles);
  $("#workflow-project").addEventListener("click", chooseProjectDirectory);
  $("#workflow-book").addEventListener("click", openNewBookModal);
  $("#export-back").addEventListener("click", () => showView("start"));
  $("#choose-source").addEventListener("click", chooseExportSource);
  $("#choose-output").addEventListener("click", chooseExportOutput);
  $("#validate-button").addEventListener("click", validateExportDocument);
  $("#export-form").addEventListener("submit", exportDocument);
  $("#cancel-button").addEventListener("click", cancelExport);
  $("#open-pdf").addEventListener("click", () => openResult(false));
  $("#reveal-pdf").addEventListener("click", () => openResult(true));
  $("#clear-recents").addEventListener("click", () => {
    state.recents = writeRecents([]);
    renderRecents();
  });

  $("#workspace-home").addEventListener("click", () => showView("start"));
  $("#workspace-new").addEventListener("click", createUntitledDocument);
  $("#workspace-open").addEventListener("click", chooseAuthoringFiles);
  $("#workspace-save").addEventListener("click", () => saveActiveDocument());
  $("#workspace-save-as").addEventListener("click", () => saveActiveDocument({ saveAs: true }));
  $("#workspace-validate").addEventListener("click", validateActiveDocument);
  $("#workspace-export").addEventListener("click", exportActiveDocument);
  $("#workspace-import-asset").addEventListener("click", importAsset);
  $("#workspace-toggle-sidebar").addEventListener("click", () => toggleWorkspacePane("sidebar"));
  $("#sidebar-resizer").addEventListener("pointerdown", (event) => beginPaneResize(event, "sidebar"));
  $("#preview-resizer").addEventListener("pointerdown", (event) => beginPaneResize(event, "preview"));
  $("#sidebar-resizer").addEventListener("keydown", (event) => resizePaneWithKeyboard(event, "sidebar"));
  $("#preview-resizer").addEventListener("keydown", (event) => resizePaneWithKeyboard(event, "preview"));
  $("#import-asset").addEventListener("click", importAsset);
  $("#refresh-assets").addEventListener("click", refreshAssets);
  $("#sidebar-open-project").addEventListener("click", chooseProjectDirectory);
  $("#refresh-project").addEventListener("click", refreshActiveProject);
  $("#run-project-search").addEventListener("click", runProjectSearch);
  $("#sidebar-new-book").addEventListener("click", openNewBookModal);
  $("#book-add-chapter").addEventListener("click", () => openChapterModal("add"));
  $("#book-validate").addEventListener("click", validateActiveBook);
  $("#book-preview").addEventListener("click", previewActiveBook);
  $("#book-export").addEventListener("click", exportActiveBook);
  $("#book-cancel-operation").addEventListener("click", cancelActiveBookOperation);
  $("#book-open-output").addEventListener("click", () => openBookOutput(false));
  $("#book-reveal-output").addEventListener("click", () => openBookOutput(true));
  $("#book-project-form").addEventListener("submit", submitNewBookProject);
  $("#cancel-book-project").addEventListener("click", closeNewBookModal);
  $("#choose-book-parent").addEventListener("click", chooseBookParent);
  $("#book-project-title-input").addEventListener("input", (event) => {
    const folder = $("#book-project-folder-input");
    if (!folder.dataset.userEdited) folder.value = folderNameFromTitle(event.target.value);
  });
  $("#book-project-folder-input").addEventListener("input", (event) => {
    event.target.dataset.userEdited = event.target.value ? "true" : "";
  });
  $("#chapter-form").addEventListener("submit", submitChapterModal);
  $("#cancel-chapter").addEventListener("click", closeChapterModal);
  $("#project-search-query").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runProjectSearch();
    }
  });
  let citationSearchTimer = null;
  $("#citation-search").addEventListener("input", () => {
    clearTimeout(citationSearchTimer);
    citationSearchTimer = setTimeout(refreshBibliography, 220);
  });
  $("#refresh-citations").addEventListener("click", refreshBibliography);
  $("#refresh-preview").addEventListener("click", refreshPreview);
  $("#auto-preview").addEventListener("change", () => {
    updatePreference({ autoPreview: $("#auto-preview").checked });
    if ($("#auto-preview").checked) refreshPreview();
  });
  $("#frontmatter-form").addEventListener("submit", applyFrontMatter);
  $("#find-query").addEventListener("input", () => { updateFindMatches(); if (state.findMatches.length) selectFindMatch(0); });
  $("#find-query").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); moveFind(event.shiftKey ? -1 : 1); } if (event.key === "Escape") closeFind(); });
  $("#find-previous").addEventListener("click", () => moveFind(-1));
  $("#find-next").addEventListener("click", () => moveFind(1));
  $("#replace-one").addEventListener("click", replaceCurrentMatch);
  $("#replace-all").addEventListener("click", replaceAllMatches);
  $("#close-find").addEventListener("click", closeFind);
  $$('[data-editor-command]').forEach((button) => button.addEventListener("click", () => {
    if (button.closest(".popover-menu")) toggleHeadingMenu(false);
    editorCommand(button.dataset.editorCommand);
  }));
  $("#heading-menu-button").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleHeadingMenu();
  });
  $("#format-find").addEventListener("click", () => openFind({ replace: false }));
  $("#heading-menu").addEventListener("keydown", (event) => {
    const items = [...$("#heading-menu").querySelectorAll("button")];
    const index = items.indexOf(document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      toggleHeadingMenu(false);
      $("#heading-menu-button").focus();
      return;
    }
    if (!["ArrowUp", "ArrowDown"].includes(event.key) || index < 0) return;
    event.preventDefault();
    const next = event.key === "ArrowDown"
      ? (index + 1) % items.length
      : (index - 1 + items.length) % items.length;
    items[next].focus();
  });
  document.addEventListener("pointerdown", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target?.closest("#heading-menu, #heading-menu-button")) toggleHeadingMenu(false);
    if (!target?.closest("#editor-context-menu")) closeEditorContextMenu();
  });
  const sidebarButtons = $$('[data-sidebar]');
  sidebarButtons.forEach((button) => {
    button.addEventListener("click", () => activateSidebar(button.dataset.sidebar));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const index = sidebarButtons.indexOf(button);
      let targetIndex = index;
      if (["ArrowUp", "ArrowLeft"].includes(event.key)) targetIndex = (index - 1 + sidebarButtons.length) % sidebarButtons.length;
      if (["ArrowDown", "ArrowRight"].includes(event.key)) targetIndex = (index + 1) % sidebarButtons.length;
      if (event.key === "Home") targetIndex = 0;
      if (event.key === "End") targetIndex = sidebarButtons.length - 1;
      const target = sidebarButtons[targetIndex];
      activateSidebar(target.dataset.sidebar);
      target.focus();
    });
  });
  $("#restore-recovery").addEventListener("click", () => resolveRecovery(true));
  $("#discard-recovery").addEventListener("click", () => resolveRecovery(false));
  $("#settings-form").addEventListener("submit", submitSettings);
  $("#close-settings").addEventListener("click", closeSettings);
  $("#settings-search").addEventListener("input", (event) => filterSettings(event.target.value));
  $("#reset-settings").addEventListener("click", resetSettings);
  $("#restart-onboarding").addEventListener("click", () => {
    closeSettings();
    state.preferences = writePreferences({ ...state.preferences, onboardingComplete: false });
    openOnboarding({ force: true });
  });
  $("#close-help").addEventListener("click", closeHelp);
  $("#help-done").addEventListener("click", closeHelp);
  $("#save-support-bundle").addEventListener("click", saveSupportBundle);
  $("#check-updates").addEventListener("click", checkUpdates);
  $("#install-update").addEventListener("click", installAvailableUpdate);
  $("#skip-onboarding").addEventListener("click", () => completeOnboarding({ runIntent: false }));
  $("#onboarding-next").addEventListener("click", onboardingNext);
  $("#onboarding-back").addEventListener("click", onboardingBack);
  $$("[data-onboarding-action]").forEach((button) => button.addEventListener("click", () => {
    state.onboardingIntent = normalizeOnboardingIntent(button.dataset.onboardingAction);
    setOnboardingStep(1);
  }));
  $("#command-query").addEventListener("input", () => {
    state.commandIndex = 0;
    renderCommandPalette();
  });
  $("#command-query").addEventListener("keydown", commandKeydown);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeEditorContextMenu();
      toggleHeadingMenu(false);
      // A mode that hides the way out has to have one.
      if (state.preferences.focusMode && !modalManager.hasOpenModal()) {
        updatePreference({ focusMode: false });
        toast(t("exitFocusMode"));
      }
    }
    if (event.key === "F1") {
      event.preventDefault();
      if (!modalManager.hasOpenModal()) openHelp();
      return;
    }
    const modifier = event.ctrlKey || event.metaKey;
    if (!modifier) return;
    const key = event.key.toLowerCase();
    if (modalManager.hasOpenModal()) return;
    const formControl = event.target instanceof Element
      && event.target.matches("input,textarea,select,[contenteditable='true']")
      && !event.target.closest(".editor-surface");
    if (formControl) return;
    if (key === "p" && event.shiftKey) {
      event.preventDefault();
      openCommandPalette();
    } else if (key === "f") {
      event.preventDefault();
      openFind({ replace: false });
    } else if (key === "h") {
      event.preventDefault();
      openFind({ replace: true });
    } else if (key === "s") {
      event.preventDefault();
      saveActiveDocument({ saveAs: event.shiftKey });
    } else if (key === "v" && event.shiftKey) {
      // Markdown is plain text; a paste that carries formatting from a browser
      // or a word processor arrives as markup nobody asked for.
      event.preventDefault();
      pasteAsPlainText();
    } else if (key === "o") {
      event.preventDefault();
      chooseAuthoringFiles();
    } else if (key === "n") {
      event.preventDefault();
      createUntitledDocument();
    } else if (
      ["b", "i", "k"].includes(key)
      && $("#workspace-view").classList.contains("active")
      // Inside the editor these are the editor's own bindings. Handling them
      // here as well ran the command twice against a selection CodeMirror had
      // already changed.
      && !(event.target instanceof Element && event.target.closest(".editor-surface"))
    ) {
      event.preventDefault();
      editorCommand(key === "b" ? "bold" : key === "i" ? "italic" : "link");
    }
  });

  window.addEventListener("beforeunload", () => {
    for (const model of state.documents) if (documentDirty(model)) saveRecovery(model);
  });
}

async function boot() {
  modalManager = createModalManager(document);
  applyInterfacePreferences();
  applyWorkspaceLayout();
  document.body.dataset.view = $("#workspace-view")?.classList.contains("active") ? "workspace" : "start";
  for (const query of ["(prefers-color-scheme: dark)", "(prefers-reduced-motion: reduce)"]) {
    try {
      matchMedia(query).addEventListener("change", () => {
        if (state.preferences.theme === "system" || state.preferences.reducedMotion === "system") {
          applyInterfacePreferences();
        }
      });
    } catch {
      // Older WebViews still use the saved explicit preference values.
    }
  }
  const textarea = $("#markdown-editor");
  const editorOptions = {
    theme: document.documentElement.dataset.theme,
    mode: editorModeForView(state.preferences.viewMode),
    typewriter: state.preferences.typewriter,
    onContextMenu: openEditorContextMenu,
    resolveAsset: resolveEditorAsset,
    getCompletions: () => activeDocument()?.projectPath === state.project?.path
      ? state.bibliographyEntries
      : [],
    onChange: onEditorInput,
    onSelectionChange: () => {
      updateEditorMetrics();
      const position = editorAdapter.lineAtOffset();
      syncPreviewToEditorLine(position.line);
    },
    onScroll: (scrollTop) => {
      if (!editorAdapter?.usesNativeLineNumbers) $("#line-gutter").scrollTop = scrollTop;
      syncPreviewFromEditorScroll(scrollTop);
    },
  };
  try {
    const { createCodeMirrorEditorAdapter } = await import("./vendor/codemirror-editor.bundle.mjs");
    editorAdapter = createCodeMirrorEditorAdapter(textarea, editorOptions);
    textarea.closest(".editor-surface")?.classList.add("professional-editor");
    textarea.closest(".editor-surface")?.setAttribute("data-editor", "codemirror");
  } catch (error) {
    console.error("CodeMirror initialization failed; using the safe textarea fallback.", error);
    editorAdapter = createEditorAdapter(textarea, editorOptions);
    textarea.closest(".editor-surface")?.setAttribute("data-editor", "textarea");
  }
  setLocale(state.locale);
  renderAdvancedOptions();
  selectPreset("general");
  bindEvents();
  renderAssets([]);
  renderProblems(null);
  renderCitations(null);
  renderBookWorkspace();
  try {
    await listen("sidecar-progress", (event) => {
      const params = event.payload?.params || {};
      const percent = Math.round(Math.max(0, Math.min(1, Number(params.fraction) || 0)) * 100);
      if (params.request_id === state.activeBookRequestId) {
        setBookOperationStatus(`${params.message || t("bookOperationRunning")} · ${percent}%`, {
          running: true,
        });
        return;
      }
      if (params.request_id !== state.activeRequestId) return;
      $("#progress-bar").style.width = `${percent}%`;
      $("#progress-label").textContent = `${percent}%`;
      if (params.message) $("#status-message").textContent = params.message;
    });
    await listen("desktop-update-progress", (event) => {
      const payload = event.payload || {};
      if (!state.updateInstalling) return;
      if (payload.event === "progress") {
        state.updateDownloaded += Number(payload.chunk_length) || 0;
        if (Number(payload.content_length) > 0) state.updateTotal = Number(payload.content_length);
        updateUi();
      } else if (payload.event === "finished") {
        state.updateDownloaded = state.updateTotal || state.updateDownloaded;
        updateUi();
      }
    });
    await listen("desktop-open-files", (event) => openAuthoringPaths(event.payload || []));
    const launchFiles = await invoke("take_launch_files");
    if (launchFiles?.length) {
      await openAuthoringPaths(launchFiles);
    } else {
      const session = readSession();
      if (session.projectPath) {
        try {
          await loadProject(session.projectPath, {
            announce: false,
            openFirstChapter: false,
          });
        } catch {
          clearProjectState();
          renderBookWorkspace();
        }
      }
      if (session.paths.length) {
        await openAuthoringPaths(session.paths);
        const active = findDocumentByPath(state.documents, session.activePath);
        if (active) activateDocument(active.id);
      }
    }
  } catch (error) {
    toast(errorText(error), "error");
  }
  await engineHealth();
  await initializeUpdater();
  const drafts = readRecoveries().filter((item) => !item.path);
  let restoredDrafts = 0;
  for (const recovery of drafts) {
    const recoveredId = recovery.key.startsWith("draft:")
      ? recovery.key.slice("draft:".length)
      : null;
    if (recoveredId && state.documents.some((model) => model.id === recoveredId)) continue;
    const model = createDocument({ content: recovery.content });
    if (recoveredId) model.id = recoveredId;
    model.title = recovery.title || model.title;
    state.documents.push(model);
    if (!state.activeDocumentId) state.activeDocumentId = model.id;
    restoredDrafts += 1;
  }
  if (restoredDrafts) {
    showView("workspace");
    renderWorkspace();
    schedulePreview(120);
  }
  if (!state.documents.length && !state.preferences.onboardingComplete) {
    openOnboarding();
  }
}

boot();
