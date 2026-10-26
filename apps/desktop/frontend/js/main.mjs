import { basename, buildDocumentParams, defaultOutputPath, validateExportSelection } from "./core/export-request.mjs";
import { createTranslator, readLocalePreference, writeLocalePreference } from "./core/i18n.mjs";
import { onboardingIntentPresentation, onboardingPrimaryActionKey, normalizeOnboardingIntent } from "./core/onboarding.mjs";
import { foldForFilter } from "./core/persian.mjs";
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
  bodyStartOffset,
  extractCitationKeys,
  extractOutline,
  parseFrontMatter,
  textMetrics,
  upsertFrontMatter,
} from "./core/markdown-analysis.mjs";
import { prefixSelectedLines, replaceSelection, wrapSelection } from "./core/editor-commands.mjs";
import { createFindSession, replaceAllLiteral } from "./core/find-replace.mjs";
import { documentImageSources, localImageDestination } from "./core/document-assets.mjs";
import { createEditorAdapter } from "./core/editor-adapter.mjs";
import { mountDocumentContent } from "./core/document-renderer.mjs";
import { interpolatePosition } from "./core/content-position.mjs";
import {
  captureDocumentContext,
  captureProjectContext,
  documentContextCurrent,
  projectContextCurrent,
} from "./core/request-context.mjs";
import { createSaveCoordinator } from "./core/save-coordinator.mjs";
import { createOutlineNavigator } from "./core/outline-navigator.mjs";
import { createDocumentMetrics } from "./core/document-metrics.mjs";
import { authoringShortcutKey } from "./core/keyboard-shortcuts.mjs";
import { createConfirmationQueue } from "./core/confirmation-queue.mjs";
import { saveDocumentsBeforeUpdate } from "./core/update-preparation.mjs";
import { prepareBookFiles } from "./core/book-preparation.mjs";
import { createSingleFlight } from "./core/single-flight.mjs";
import { beginCancellationHandoff } from "./core/task-handoff.mjs";
import { diagnosticLines, inlineDiagnosticsForDocument } from "./core/diagnostics.mjs";
import { bookTaskBlocked, claimBookTask } from "./core/book-task-state.mjs";
import {
  DEFAULT_PREFERENCES,
  DOCUMENT_ZOOM_MIN,
  DOCUMENT_ZOOM_MAX,
  applyPreferences,
  editorModeForView,
  nextDocumentZoom,
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
import { documentNavigationEntries } from "./core/document-navigation.mjs";
import { createNavigationPicker } from "./core/navigation-picker.mjs";
import { fitToolbarGroups } from "./core/toolbar-overflow.mjs";
import { createModalManager, focusableElements } from "./core/modal-manager.mjs";
import { createPageDeck } from "./preview/page-deck.mjs";
import { typesetPreviewMath } from "./preview/math.mjs";
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
  cancelledExportRequestId: null,
  outputResult: null,
  exportReturnView: "start",
  bookOutputPath: null,
  recents: readRecents(),
  documents: [],
  activeDocumentId: null,
  documentActivationSequence: 0,
  previewTimer: null,
  recoveryTimers: new Map(),
  previewSequence: 0,
  validationSequence: 0,
  assetSequence: 0,
  pendingRecovery: null,
  recoveryQueue: [],
  activeSidebar: "frontmatter",
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
  engineMethods: null,
  updateStatus: null,
  updateCheck: null,
  updateInstalling: false,
  updatePreparing: false,
  updateDownloaded: 0,
  updateTotal: 0,
};
let editorAdapter = null;
let outlineNavigator = null;
let outlineLocale = null;
const documentMetrics = createDocumentMetrics();
let modalManager = null;
let navigationPicker = null;
const documentImageScopes = new WeakMap();
let imageScopeTimer = null;
const saveCoordinator = createSaveCoordinator({ isDirty: documentDirty });
const findSession = createFindSession();
const askConfirmation = createConfirmationQueue(presentConfirmation);
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

function documentEditable() {
  const model = activeDocument();
  return Boolean(model && !model.readOnly && !state.updateInstalling && !state.bookPreparing && effectiveViewMode() !== "read");
}

function effectiveViewMode() {
  return activeDocument() && !isMarkdownModel(activeDocument()) ? "source" : state.preferences.viewMode;
}

function contentViewVisible() {
  return effectiveViewMode() === "read" || (isMarkdownModel(activeDocument())
    && previewVisibleForView(effectiveViewMode(), state.preferences.sidePreview));
}

function focusDocument() {
  if (effectiveViewMode() === "read") $("#reading-document")?.focus({ preventScroll: true });
  else currentEditor().focus();
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
  editorAdapter?.setLocale?.(state.locale, editorStrings());
  renderDocumentViewControls();
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
  retranslateExportPreview();
  if (modalManager?.isOpen($("#command-modal"))) renderCommandPalette();
}

function showView(name) {
  // Leaving the workspace is a newer intent than any pending file activation.
  if (name !== "workspace") state.documentActivationSequence += 1;
  $$(".view").forEach((element) => element.classList.remove("active"));
  $(`#${name}-view`)?.classList.add("active");
  document.body.dataset.view = name;
  if (name !== "workspace" && state.preferences.focusMode) updatePreference({ focusMode: false });
  if (name === "workspace") applyWorkspaceLayout();
  $("#app-main")?.focus({ preventScroll: true });
  syncExportToastPlacement();
}


/** Keep transient notifications above the destination and export controls.
 * The dock can wrap when Cancel appears, the language changes, or the window
 * is resized. Its measured top is therefore the boundary, rather than a
 * guessed footer height that can cover the controls in a smaller window.
 */
function syncExportToastPlacement() {
  const region = $("#toast-region");
  const dock = $("#export-view .export-dock");
  if (!region || !dock) return;
  if (document.body.dataset.view !== "export") {
    region.style.removeProperty("--export-toast-bottom");
    return;
  }
  const top = dock.getBoundingClientRect().top;
  region.style.setProperty("--export-toast-bottom", `${Math.ceil(Math.max(12, window.innerHeight - top + 12))}px`);
}


/**
 * Map a Markdown image path to a URL the webview may load.
 *
 * Only paths that resolve inside the open document's own directory are turned
 * into asset URLs; the native side grants a bounded inventory of image files.
 * Remote and absolute sources are declined here rather than
 * fetched, which keeps the offline guarantee the app makes on its own footer.
 */
function resolveEditorAsset(source) {
  const raw = localImageDestination(source);
  if (!raw) return null;
  const model = activeDocument();
  if (!model?.path) return null;
  const granted = documentImageScopes.get(model);
  if (granted?.path !== model.path || !granted.sources.has(raw)) return null;
  const separator = model.path.includes("\\") ? "\\" : "/";
  const directory = model.path.slice(0, model.path.lastIndexOf(separator));
  if (!directory) return null;

  const normalized = raw;
  // A path that climbs out of the document directory is outside the scope the
  // native side allowed, so it would fail to load anyway.
  if (normalized.startsWith("/") || normalized.split("/").includes("..")) return null;
  const absolute = `${directory}${separator}${normalized}`;
  try {
    return globalThis.__TAURI__?.core?.convertFileSrc?.(absolute) || null;
  } catch {
    return null;
  }
}

/**
 * Apply the current view mode.
 *
 * Activity and layout are independent: Write/Source choose editing, Read
 * reviews the same content. Side preview compares either editing view with it.
 */
function applyViewMode() {
  toggleHeadingMenu(false);
  toggleInsertMenu(false);
  toggleFormatOverflowMenu(false);
  toggleWritingAppearance(false);
  const mode = effectiveViewMode();
  editorAdapter?.setMode?.(editorModeForView(mode));
  editorAdapter?.setReadOnly?.(Boolean(activeDocument()?.readOnly) || mode === "read" || state.updateInstalling || Boolean(state.bookPreparing));

  const showPreview = isMarkdownModel(activeDocument()) && previewVisibleForView(mode, state.preferences.sidePreview);
  if (state.workspaceLayout.previewOpen !== showPreview) {
    state.workspaceLayout = { ...state.workspaceLayout, previewOpen: showPreview };
    applyWorkspaceLayout({ persist: true });
  }

  for (const button of $$("button[data-view-mode]")) {
    const selected = button.dataset.viewMode === mode;
    button.setAttribute("aria-checked", String(selected));
    button.tabIndex = selected ? 0 : -1;
    button.classList.toggle("selected", selected);
    button.disabled = !activeDocument() || (mode === "source" && !isMarkdownModel(activeDocument()) && button.dataset.viewMode !== "source");
  }
  const sidePreview = $("#workspace-toggle-preview");
  if (sidePreview) {
    sidePreview.hidden = mode === "read";
    sidePreview.disabled = !isMarkdownModel(activeDocument());
    sidePreview.setAttribute("aria-pressed", String(showPreview));
    sidePreview.setAttribute("aria-expanded", String(showPreview));
  }
  const surface = $(".editor-pane");
  if (surface) surface.dataset.viewMode = mode;
  if ($("#reading-surface")) $("#reading-surface").hidden = mode !== "read";
  if ($(".editor-surface")) $(".editor-surface").inert = mode === "read";
  $("#workspace-view")?.setAttribute("data-view-mode", mode);
  updateAuthoringMode(activeDocument());
  if (isMarkdownModel(activeDocument())) loadFrontMatterForm(activeDocument());
  renderContentStatus();
}

function setViewMode(mode) {
  const previousMode = effectiveViewMode();
  if (activeDocument() && !isMarkdownModel(activeDocument()) && mode !== "source") return;
  if (mode === previousMode) return;
  const previousLine = previousMode === "read" ? readingSourceLine() : null;
  if (mode === "read" && previousMode !== "read" && activeDocument()) {
    pendingReadingLine = { id: activeDocument().id, line: editorAdapter?.firstVisibleLine?.() || 1 };
  }
  // Keep command-palette/deep-link compatibility with the old combined mode.
  if (mode === "split") {
    updatePreference({ viewMode: "source", sidePreview: true });
    schedulePreview(120, { entering: true });
    editorAdapter?.focus?.();
    return;
  }
  if (mode === "read" && activeDocument() && !isMarkdownModel(activeDocument())) mode = "source";
  if (state.preferences.viewMode === "read" && readingDocumentId) {
    readingScroll.set(readingDocumentId, $("#reading-document")?.scrollTop || 0);
  }
  updatePreference({ viewMode: mode });
  if (mode === "read") renderReading(activeDocument());
  else if (previousLine !== null) requestAnimationFrame(() => editorAdapter?.scrollToLine?.(previousLine));
  if (contentViewVisible()) schedulePreview(120, { entering: true });
  if (mode === "read") $("#reading-document")?.focus({ preventScroll: true });
  else editorAdapter?.focus?.();
}

function toggleSidePreview() {
  updatePreference({ sidePreview: !state.preferences.sidePreview });
  if (contentViewVisible()) schedulePreview(120, { entering: true });
  focusDocument();
}

function applyInterfacePreferences({ persist = false } = {}) {
  if (persist) state.preferences = writePreferences(state.preferences);
  state.preferences = applyPreferences(document.documentElement, state.preferences);
  renderDocumentViewControls();
  // The editor keeps its own light/dark state so CodeMirror's floating panels
  // match the workspace.
  editorAdapter?.setTheme?.(document.documentElement.dataset.theme);
  editorAdapter?.setTypewriter?.(state.preferences.typewriter);
  $("#workspace-focus")?.setAttribute("aria-pressed", String(state.preferences.focusMode));
  applyViewMode();
  for (const autoPreview of $$('[data-content-auto]')) autoPreview.checked = Boolean(state.preferences.autoPreview);
}

function updatePreference(next, { persist = true } = {}) {
  state.preferences = { ...state.preferences, ...next };
  if (persist) state.preferences = writePreferences(state.preferences);
  applyInterfacePreferences();
}

function renderDocumentViewControls() {
  if ($("#writing-font")) $("#writing-font").value = state.preferences.writingFont;
  if ($("#writing-density")) $("#writing-density").value = state.preferences.writingDensity;
  for (const selector of ["#writing-font", "#writing-density"]) if ($(selector)) $(selector).disabled = effectiveViewMode() === "source";
  if ($("#writing-zoom")) $("#writing-zoom").value = String(state.preferences.documentZoom);
  if ($("#writing-zoom-label")) $("#writing-zoom-label").textContent = `${state.preferences.documentZoom}%`;
  const zoom = state.preferences.documentZoom;
  const reset = $("#document-zoom-reset");
  if (reset) {
    reset.textContent = `${zoom}%`;
    reset.setAttribute("aria-label", `${t("documentTextSize")}: ${zoom}%. ${t("resetDocumentZoom")}`);
    reset.title = `${t("resetDocumentZoom")} (Ctrl+0)`;
  }
  const smaller = $("#document-zoom-out");
  const larger = $("#document-zoom-in");
  if (smaller) smaller.disabled = zoom <= DOCUMENT_ZOOM_MIN;
  if (larger) larger.disabled = zoom >= DOCUMENT_ZOOM_MAX;
  const width = $("#document-toggle-width");
  if (width) {
    const full = state.preferences.writingWidth === "full";
    width.setAttribute("aria-pressed", String(!full));
    const label = t(full ? "useReadableWidth" : "useFullWidth");
    width.title = label;
    width.setAttribute("aria-label", label);
    $("#document-width-label").textContent = t(full ? "fullColumn" : state.preferences.writingWidth === "wide" ? "wideColumn" : "comfortableColumn");
  }
}

function updateDocumentView(next) {
  // A display adjustment does not reload the article, rerun the engine, or
  // touch Markdown. In particular a reader can resize text while scanning a
  // long document without losing the loaded result.
  state.preferences = writePreferences({ ...state.preferences, ...next });
  applyPreferences(document.documentElement, state.preferences);
  renderDocumentViewControls();
  editorAdapter?.refreshLayout?.();
}

function changeDocumentZoom(direction) {
  updateDocumentView({ documentZoom: direction === 0 ? 100 : nextDocumentZoom(state.preferences.documentZoom, direction) });
}

function applyWorkspaceLayout({ persist = false } = {}) {
  const grid = $(".authoring-grid");
  const workspace = $("#workspace-view");
  if (!grid || !workspace) return;
  if (persist) state.workspaceLayout = writeWorkspaceLayout(state.workspaceLayout);
  for (const element of [workspace, grid]) {
    element.dataset.filesOpen = String(state.workspaceLayout.filesOpen);
    element.dataset.formattingOpen = String(state.workspaceLayout.formattingOpen);
    element.dataset.sidebarOpen = String(state.workspaceLayout.sidebarOpen);
    element.dataset.previewOpen = String(state.workspaceLayout.previewOpen);
    element.style.setProperty("--sidebar-width", `${state.workspaceLayout.sidebarWidth}px`);
    element.style.setProperty("--files-width", `${state.workspaceLayout.filesWidth}px`);
    element.style.setProperty("--preview-width", `${state.workspaceLayout.previewWidth}px`);
  }
  const sidebarButton = $("#workspace-toggle-sidebar");
  const sidebarResizer = $("#sidebar-resizer");
  const previewResizer = $("#preview-resizer");
  $("#workspace-toggle-files")?.setAttribute("aria-pressed", String(state.workspaceLayout.filesOpen));
  $("#workspace-toggle-formatting")?.setAttribute("aria-pressed", String(state.workspaceLayout.formattingOpen));
  $("#workspace-toggle-formatting")?.setAttribute("aria-expanded", String(state.workspaceLayout.formattingOpen));
  $("#file-resizer")?.setAttribute("aria-valuenow", String(state.workspaceLayout.filesWidth));
  if ($("#file-navigator")) $("#file-navigator").inert = !state.workspaceLayout.filesOpen;
  if ($("#author-sidebar")) $("#author-sidebar").inert = !state.workspaceLayout.sidebarOpen;
  if (sidebarButton) {
    sidebarButton.setAttribute("aria-pressed", String(state.workspaceLayout.sidebarOpen));
    sidebarButton.setAttribute("aria-expanded", String(state.workspaceLayout.sidebarOpen));
  }
  if (sidebarResizer) sidebarResizer.setAttribute("aria-valuenow", String(state.workspaceLayout.sidebarWidth));
  if (previewResizer) previewResizer.setAttribute("aria-valuenow", String(state.workspaceLayout.previewWidth));
  applyNavigatorContext();
}

function applyNavigatorContext() {
  const markdown = isMarkdownModel(activeDocument());
  const tab = markdown ? state.workspaceLayout.navigatorTab : "files";
  for (const button of $$("[data-navigator-tab]")) {
    const active = button.dataset.navigatorTab === tab;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    button.disabled = button.dataset.navigatorTab === "outline" && !markdown;
  }
  for (const [name, selector] of [["files", "#navigator-panel-files"], ["outline", "#sidebar-panel-outline"]]) {
    const panel = $(selector);
    if (panel) { panel.hidden = tab !== name; panel.inert = tab !== name; }
  }
  $(".navigator-footer")?.classList.toggle("hidden", tab === "outline");
}

function activateNavigator(name) {
  if (name === "outline" && !isMarkdownModel(activeDocument())) return;
  state.workspaceLayout.navigatorTab = name;
  state.workspaceLayout.filesOpen = true;
  if (matchMedia("(max-width: 1100px)").matches) state.workspaceLayout.sidebarOpen = false;
  applyWorkspaceLayout({ persist: true });
}

function toggleWorkspacePane(name) {
  const key = `${name}Open`;
  state.workspaceLayout = { ...state.workspaceLayout, [key]: !state.workspaceLayout[key] };
  if (matchMedia("(max-width: 1100px)").matches && state.workspaceLayout[key]) {
    if (name === "files") state.workspaceLayout.sidebarOpen = false;
    if (name === "sidebar") state.workspaceLayout.filesOpen = false;
  }
  applyWorkspaceLayout({ persist: true });
  if (!state.workspaceLayout[key]) focusDocument();
  if (name === "preview" && state.workspaceLayout.previewOpen) schedulePreview(80);
}

function setWorkspacePaneWidth(name, value, { persist = false } = {}) {
  const key = `${name}Width`;
  state.workspaceLayout = {
    ...state.workspaceLayout,
    [key]: clampWorkspaceWidth(name, value),
  };
  applyWorkspaceLayout({ persist });
}

/**
 * Which way a pane grows when the pointer moves right.
 *
 * The side bar sits on the inline start of the workbench and the preview on
 * the inline end, so in a right-to-left interface both are on the opposite
 * physical edge and a drag that widened a pane now has to narrow it. Reading
 * the sign from the document's direction keeps the handle following the
 * pointer in either language instead of running away from it.
 */
function paneResizeSign(name) {
  const mirrored = document.documentElement.dir === "rtl" ? -1 : 1;
  return (name === "files" ? 1 : -1) * mirrored;
}

let finishPaneResize = null;
function beginPaneResize(event, name) {
  if (event.button !== 0 || matchMedia("(max-width: 1100px)").matches) return;
  finishPaneResize?.();
  event.preventDefault();
  const handle = event.currentTarget;
  const startX = event.clientX;
  const sign = paneResizeSign(name);
  const startWidth = state.workspaceLayout[`${name}Width`];
  handle.classList.add("is-dragging");
  document.documentElement.dataset.paneResizing = name;
  handle.setPointerCapture?.(event.pointerId);
  const move = (moveEvent) => {
    if (moveEvent.pointerId !== event.pointerId) return;
    const delta = moveEvent.clientX - startX;
    setWorkspacePaneWidth(name, startWidth + sign * delta);
  };
  let finished = false;
  const finish = (revert = false) => {
    if (finished) return;
    finished = true;
    if (revert) setWorkspacePaneWidth(name, startWidth);
    handle.classList.remove("is-dragging");
    delete document.documentElement.dataset.paneResizing;
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", end);
    handle.removeEventListener("pointercancel", end);
    handle.removeEventListener("lostpointercapture", end);
    document.removeEventListener("keydown", keydown, true);
    window.removeEventListener("blur", end);
    if (handle.hasPointerCapture?.(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    state.workspaceLayout = writeWorkspaceLayout(state.workspaceLayout);
    finishPaneResize = null;
  };
  const end = () => finish();
  const keydown = (keyEvent) => {
    if (keyEvent.key !== "Escape") return;
    keyEvent.preventDefault();
    keyEvent.stopImmediatePropagation();
    finish(true);
  };
  finishPaneResize = end;
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
  handle.addEventListener("lostpointercapture", end);
  document.addEventListener("keydown", keydown, true);
  window.addEventListener("blur", end);
}

function resizePaneWithKeyboard(event, name) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const current = state.workspaceLayout[`${name}Width`];
  const sign = paneResizeSign(name);
  let next = current;
  if (event.key === "ArrowLeft") next -= sign * 16;
  if (event.key === "ArrowRight") next += sign * 16;
  if (event.key === "Home") next = clampWorkspaceWidth(name, 0);
  if (event.key === "End") next = clampWorkspaceWidth(name, 9999);
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
    button.querySelector("i").replaceChildren(spriteIcon(template.symbol));
    button.querySelector("strong").textContent = t(template.titleKey);
    button.querySelector("small").textContent = t(template.descriptionKey);
    button.addEventListener("click", () => createDocumentFromTemplate(template.id));
    container.append(button);
  }
}

function createDocumentFromTemplate(templateId = "blank") {
  if (state.preferences.viewMode === "read") updatePreference({ viewMode: "write" });
  state.documentActivationSequence += 1;
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
  const zoomSetting = $("#setting-document-zoom");
  if (zoomSetting) zoomSetting.value = String(state.preferences.documentZoom);
  $("#setting-motion").value = state.preferences.reducedMotion;
  $("#setting-auto-preview").checked = state.preferences.autoPreview;
  $("#setting-typewriter").checked = state.preferences.typewriter;
  if ($("#setting-writing-width")) $("#setting-writing-width").value = state.preferences.writingWidth;
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
  // Read both sides as the same Persian, so a setting is found however its
  // yeh, kaf and joiners were typed.
  const needle = foldForFilter(query);
  let visible = 0;
  $$(".settings-section").forEach((section) => {
    const haystack = foldForFilter(
      `${section.dataset.settingsTerms || ""} ${section.textContent || ""}`,
    );
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
    documentZoom: Number($("#setting-document-zoom").value),
    writingWidth: $("#setting-writing-width")?.value || "full",
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
  // The first control is the close button in the heading, which is where a
  // dialog should open. Naming the one at the far end scrolled past the title.
  modalManager.open($("#help-modal"));
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
    $("#update-state").textContent = t(state.updatePreparing ? "updateSavingDocuments" : "updateInstalling");
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
  if (state.activeRequestId || state.activeBookRequestId || state.activeProjectSearchRequestId) {
    toast(t("updateFinishTasks"), "info");
    return;
  }
  state.updateInstalling = true;
  state.updatePreparing = true;
  state.updateDownloaded = 0;
  state.updateTotal = 0;
  updateAuthoringMode(activeDocument());
  updateUi();
  try {
    const ready = await saveDocumentsBeforeUpdate({
      getDocuments: () => state.documents,
      isDirty: documentDirty,
      confirm: () => askConfirmation({
        title: t("updateSaveDocuments"),
        message: t("updateSaveDocumentsHelp"),
        confirmLabel: t("saveAndInstallUpdate"),
      }),
      save: (model) => saveCoordinator.save(model, () => persistDocumentModel(model)),
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
    updateAuthoringMode(activeDocument());
    if ($("#update-state").dataset.state !== "error") updateUi();
    $("#update-progress").classList.add("hidden");
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
  const canRender = hasDocument && isMarkdownModel(activeDocument());
  const canEdit = documentEditable() && isMarkdownModel(activeDocument());
  return [
    ...[
      ["bold", "bold", "pencil"], ["italic", "italic", "pencil"], ["strike", "strikethrough", "pencil"],
      ["link", "link", "link"], ["code", "code", "source"], ["bullet-list", "bulletList", "outline"],
      ["ordered-list", "orderedList", "outline"], ["task-list", "taskList", "quality"], ["quote", "blockQuote", "quote"],
      ["table", "insertTable", "table"], ["code-block", "codeBlock", "source"], ["callout", "insertCallout", "callout"],
      ["rule", "horizontalRule", "rule"],
    ].map(([command, label, symbol]) => ({ id: `format-${command}`, symbol, label: t(label), keywords: `${command} markdown format قالب بندی`, priority: 45, enabled: canEdit, run: () => editorCommand(command) })),
    ...[1, 2, 3, 4, 5, 6].map((level) => ({ id: `format-heading-${level}`, symbol: "outline", label: `${t("heading")} ${level}`, keywords: `heading h${level} عنوان`, priority: 43, enabled: canEdit, run: () => editorCommand(`heading-${level}`) })),
    { id: "insert-image", symbol: "image", label: t("insertImage"), keywords: "image photo تصویر عکس", priority: 45, enabled: canEdit, run: () => importAsset() },
    { id: "quick-open", symbol: "folder", label: t("quickOpen"), keywords: "switch file document فایل سند", shortcut: "Ctrl P", priority: 94, run: () => navigationPicker.open("files") },
    { id: "go-heading", symbol: "outline", label: t("goToHeading"), keywords: "heading outline section عنوان بخش", shortcut: "Ctrl Shift O", priority: 59, enabled: canRender, run: () => navigationPicker.open("headings") },
    { id: "files-pane", symbol: "panel-left", label: t("toggleFiles"), keywords: "files explorer navigator فایل", priority: 38, run: () => toggleWorkspacePane("files") },
    { id: "inspector-pane", symbol: "outline", label: t("toggleSidebar"), keywords: "outline inspector properties ساختار مشخصات", priority: 38, run: () => toggleWorkspacePane("sidebar") },
    { id: "formatting-pane", symbol: "pencil", label: t("toggleFormatting"), keywords: "format toolbar tools قالب بندی", priority: 38, enabled: canEdit, run: () => toggleWorkspacePane("formatting") },
    { id: "new", symbol: "plus", label: t("commandNewDocument"), keywords: "new document markdown", shortcut: "Ctrl N", priority: 100, run: () => createUntitledDocument() },
    { id: "open", symbol: "file", label: t("commandOpenDocument"), keywords: "open file markdown", shortcut: "Ctrl O", priority: 95, run: () => chooseAuthoringFiles() },
    { id: "project", symbol: "folder", label: t("commandOpenProject"), keywords: "open folder workspace project", priority: 80, run: () => chooseProjectDirectory() },
    { id: "book", symbol: "book", label: t("commandNewBook"), keywords: "book thesis chapters project", priority: 75, run: () => openNewBookModal() },
    { id: "save", symbol: "save", label: t("commandSave"), keywords: "save write", shortcut: "Ctrl S", priority: 90, enabled: hasDocument, run: () => saveActiveDocument() },
    { id: "save-as", symbol: "save-as", label: t("commandSaveAs"), keywords: "save as copy", shortcut: "Ctrl Shift S", priority: 70, enabled: hasDocument, run: () => saveActiveDocument({ saveAs: true }) },
    { id: "validate", symbol: "quality", label: t("commandValidate"), keywords: "check problems diagnostics", priority: 65, enabled: canRender, run: () => validateActiveDocument() },
    { id: "export", symbol: "export", label: t("commandExport"), keywords: "pdf publish render", priority: 85, enabled: canRender, run: () => exportActiveDocument() },
    { id: "find", symbol: "search", label: t("commandFind"), keywords: "find replace search", shortcut: "Ctrl F", priority: 60, enabled: hasDocument, run: () => openFind({ replace: false }) },
    { id: "settings", symbol: "settings", label: t("commandSettings"), keywords: "preferences appearance accessibility", priority: 40, run: () => openSettings() },
    { id: "support-bundle", symbol: "archive", label: t("commandSupportBundle"), keywords: "support diagnostics troubleshooting zip privacy", priority: 38, run: () => saveSupportBundle() },
    { id: "updates", symbol: "update", label: t("commandCheckUpdates"), keywords: "update upgrade release version", priority: 37, run: () => { openSettings(); setTimeout(() => checkUpdates(), 0); } },
    // The constructs with no button of their own, so the palette can reach
    // them by name as well as the Insert menu by picture.
    { id: "insert-footnote", symbol: "footnote", label: t("insertFootnote"), keywords: "footnote note reference پانویس", priority: 46, enabled: canEdit, run: () => editorCommand("footnote") },
    { id: "insert-math-inline", symbol: "maths", label: t("insertMathInline"), keywords: "math formula equation latex فرمول ریاضی", priority: 45, enabled: canEdit, run: () => editorCommand("math-inline") },
    { id: "insert-math-block", symbol: "maths-block", label: t("insertMathBlock"), keywords: "math display block equation فرمول", priority: 44, enabled: canEdit, run: () => editorCommand("math-block") },
    { id: "insert-diagram", symbol: "diagram", label: t("insertDiagram"), keywords: "mermaid diagram graph chart نمودار", priority: 43, enabled: canEdit, run: () => editorCommand("mermaid") },
    { id: "insert-highlight", symbol: "highlight", label: t("insertHighlight"), keywords: "highlight mark هایلایت", priority: 43, enabled: canEdit, run: () => editorCommand("highlight") },
    { id: "view-write", symbol: "pencil", label: t("viewWrite"), keywords: "write live formatted wysiwyg نوشتن", priority: 42, enabled: canRender, run: () => setViewMode("write") },
    { id: "view-source", symbol: "source", label: t("viewSource"), keywords: "source raw markdown سورس", priority: 41, enabled: hasDocument, run: () => setViewMode("source") },
    { id: "view-read", symbol: "book", label: t("viewRead"), keywords: "reading readonly خواندن مطالعه", priority: 41, enabled: canRender, run: () => setViewMode("read") },
    { id: "view-split", symbol: "panel-right", label: t("sidePreview"), keywords: "split preview compare دوستونه پیش نمایش", priority: 40, enabled: canRender && effectiveViewMode() !== "read", run: toggleSidePreview },
    { id: "view-guide", symbol: "help", label: t("viewGuide"), keywords: "view mode source read preview راهنمای نما", priority: 40, run: () => modalManager.open($("#view-guide-modal")) },
    { id: "typewriter", symbol: "typewriter", label: t("typewriterMode"), keywords: "typewriter scroll centre writing ماشین تحریر", priority: 39, run: () => updatePreference({ typewriter: !state.preferences.typewriter }) },
    { id: "focus-mode", symbol: "focus", label: t("focusMode"), keywords: "focus distraction free zen تمرکز", priority: 39, run: () => updatePreference({ focusMode: !state.preferences.focusMode }) },
    { id: "document-zoom-in", symbol: "zoom-in", label: t("increaseDocumentText"), keywords: "zoom text font larger اندازه متن بزرگ", shortcut: "Ctrl +", priority: 38, run: () => changeDocumentZoom(1) },
    { id: "document-zoom-out", symbol: "zoom-out", label: t("decreaseDocumentText"), keywords: "zoom text font smaller اندازه متن کوچک", shortcut: "Ctrl -", priority: 38, run: () => changeDocumentZoom(-1) },
    { id: "document-zoom-reset", symbol: "zoom-in", label: t("resetDocumentZoom"), keywords: "zoom text font reset اندازه متن", shortcut: "Ctrl 0", priority: 37, run: () => changeDocumentZoom(0) },
    { id: "document-full-width", symbol: "focus", label: t("useFullWidth"), keywords: "document width full canvas عرض تمام", priority: 37, run: () => updateDocumentView({ writingWidth: "full" }) },
    { id: "document-readable-width", symbol: "book", label: t("useReadableWidth"), keywords: "document width readable column عرض ستون خوانا", priority: 37, run: () => updateDocumentView({ writingWidth: "readable" }) },
    { id: "help", symbol: "help", label: t("commandHelp"), keywords: "help shortcuts guide onboarding", shortcut: "F1", priority: 35, run: () => openHelp() },
    { id: "home", symbol: "home", label: t("commandHome"), keywords: "start home center", priority: 20, run: () => showView("start") },
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
    button.querySelector("i").replaceChildren(spriteIcon(command.symbol || "file"));
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

/**
 * How many notices may stand at once, and how long each one waits.
 *
 * Every call used to append a card and nothing ever looked at what was already
 * there. Five saves left five identical "Settings saved" cards stacked over the
 * sidebar, and a busy moment could put seven on screen at once — a wall of text
 * that says one thing.
 */
const TOAST_LIMIT = 3;
const TOAST_TTL = 4200;

function dismissToast(element) {
  if (!element) return;
  clearTimeout(Number(element.dataset.toastTimer || 0));
  element.remove();
}

function toast(message, kind = "info") {
  const region = $("#toast-region");
  if (!region) return;
  const text = String(message ?? "");

  // A repeat counts up on the notice already standing rather than adding
  // another copy of it.
  const repeat = [...region.children].find(
    (item) => item.dataset.toastMessage === text && item.dataset.toastKind === kind,
  );
  if (repeat) {
    const count = Number(repeat.dataset.toastCount || "1") + 1;
    repeat.dataset.toastCount = String(count);
    const badge = repeat.querySelector(".toast-count");
    if (badge) {
      badge.textContent = `\u00d7${count}`;
      badge.hidden = false;
    }
    clearTimeout(Number(repeat.dataset.toastTimer || 0));
    repeat.dataset.toastTimer = String(setTimeout(() => dismissToast(repeat), TOAST_TTL));
    return;
  }

  // Nothing is learned from a fourth card; the oldest makes room.
  while (region.children.length >= TOAST_LIMIT) dismissToast(region.firstElementChild);

  const element = document.createElement("div");
  element.className = `toast ${kind}`;
  element.setAttribute("role", kind === "error" ? "alert" : "status");
  element.setAttribute("aria-atomic", "true");
  element.dataset.toastMessage = text;
  element.dataset.toastKind = kind;
  element.dataset.toastCount = "1";
  const label = document.createElement("span");
  label.className = "toast-text";
  // A notice can be either language: an engine or filesystem message arrives in
  // English even when the interface is Persian, and in an RTL container its
  // full stop was drawn at the head of the sentence. The run decides its own
  // direction.
  label.dir = "auto";
  label.textContent = text;
  const badge = document.createElement("span");
  badge.className = "toast-count";
  badge.hidden = true;
  element.append(label, badge);
  region.append(element);
  element.dataset.toastTimer = String(setTimeout(() => dismissToast(element), TOAST_TTL));
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
/** What the export badge draws, per state. */
const STATUS_SYMBOLS = {
  idle: "file",
  working: "refresh",
  success: "check",
  error: "alert",
};

function setExportStatus(kind, titleKey, message, diagnostics = []) {
  const visual = $("#status-visual");
  visual.dataset.state = kind;
  // Colour alone cannot carry this: a failed export used to show a tick in
  // red, which reads as success to anyone who does not separate the two hues.
  $("#status-symbol")?.replaceChildren(spriteIcon(STATUS_SYMBOLS[kind] || "file"));
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
  $("#export-form").setAttribute("aria-busy", String(enabled));
  for (const control of [...$("#export-form").querySelectorAll("button,input,select,textarea"), $("#choose-output")]) {
    if (enabled) {
      if (!("disabledBeforeExport" in control.dataset)) control.dataset.disabledBeforeExport = String(control.disabled);
      control.disabled = true;
    } else if ("disabledBeforeExport" in control.dataset) {
      control.disabled = control.dataset.disabledBeforeExport === "true";
      delete control.dataset.disabledBeforeExport;
    }
  }
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

/**
 * An icon from the sprite in `index.html`.
 *
 * `<use>` rather than an inline copy of the path: the sprite is already in the
 * document, and duplicating a symbol per button is how two drawings of the
 * same idea drift apart.
 */
function spriteIcon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ui-icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.append(use);
  return svg;
}

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
  // Three states, not two.
  //
  // Choosing a preset copies its options into the working set, so every one of
  // them read as "set by you": the accent rule down the row, the reset dot,
  // the group's changed-count badge. A value the preset supplied looked
  // exactly like one the user had overridden, and the summary's "N changed"
  // — which compares against the preset — disagreed with both.
  //
  // Worse, the dot on such a row did not do what it looked like. It deleted
  // the value, so the engine fell back to `mardas.toml` or its own default
  // rather than to the preset the user had picked: pressing "reset" on
  // Style: Modern quietly changed the output away from Modern.
  const presetOptions = presetById(state.presetId).options;
  const hasValue = advancedValues.has(field.key);
  const fromPreset = hasValue
    && field.key in presetOptions
    && String(advancedValues.get(field.key)) === String(presetOptions[field.key]);
  const isSet = hasValue && !fromPreset;
  row.dataset.modified = String(isSet);
  row.dataset.source = isSet ? "override" : hasValue ? "preset" : "inherited";

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
  if (fromPreset) {
    const badge = document.createElement("span");
    badge.className = "option-badge from-preset";
    badge.textContent = t("fromPreset");
    head.append(badge);
  }
  if (isSet) {
    // Back to the preset's value where it has one, and to inherited where it
    // does not — which is what "reset" has to mean on a screen whose second
    // step is choosing a preset.
    const restores = field.key in presetOptions;
    const label = t(restores ? "resetToPreset" : "resetOption");
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "option-reset";
    reset.title = label;
    reset.setAttribute("aria-label", `${label}: ${t(`opt.${field.key}`)}`);
    reset.append(spriteIcon("close"));
    reset.addEventListener("click", () => setOptionValue(field.key, presetOptions[field.key]));
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
    button.id = `option-tab-${group.id}`;
    button.setAttribute("aria-controls", "option-pane");
    button.setAttribute("aria-selected", String(group.id === activeOptionGroup && !optionSearchQuery));
    button.tabIndex = group.id === activeOptionGroup ? 0 : -1;
    button.dataset.group = group.id;

    const icon = document.createElement("span");
    icon.className = "option-rail-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.append(spriteIcon(group.icon));
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
      $(`#option-tab-${group.id}`)?.focus({ preventScroll: true });
    });
    rail.append(button);
  }
}

function renderOptionPane() {
  const pane = $("#option-pane");
  if (!pane) return;
  pane.replaceChildren();
  pane.setAttribute("role", optionSearchQuery ? "region" : "tabpanel");

  if (optionSearchQuery) {
    pane.setAttribute("aria-labelledby", "option-search-label");
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
  pane.setAttribute("aria-labelledby", `option-tab-${group.id}`);
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
// The engine takes one job at a time, so previews queue behind each other
// rather than compete for it.
const exportPreviewFlight = createSingleFlight(() => drawExportPreview());

/**
 * Stand the preview down before a job the user actually asked for.
 *
 * The engine runs one job at a time and answers a second with SERVER_BUSY, so
 * a preview still rendering when "Create PDF" is pressed would fail the export.
 * The preview is speculative work; it yields.
 *
 * Cancelling it is a request, not a guarantee: composing the preview page is
 * pure Markdown work that never receives the cancellation callback, so it runs
 * to completion regardless. On a long document that is seconds during which
 * the engine is still busy, which is exactly how an export used to fail. So
 * after asking, wait for the engine to actually come free.
 */
async function releaseEngineForJob() {
  if (exportPreviewTimer) {
    clearTimeout(exportPreviewTimer);
    exportPreviewTimer = null;
  }
  exportPreviewSequence += 1;
  const pending = exportPreviewRequestId;
  exportPreviewRequestId = null;
  if (pending) {
    try {
      await invoke("sidecar_cancel", { request_id: pending });
    } catch {
      // Already finished, or never started; either way the engine is free.
    }
  }
  await exportPreviewFlight.drain();
}

/* The export preview is the one surface the language sweep cannot reach.
 *
 * `setLocale` retranslates everything carrying `data-i18n`, but the deck draws
 * into an iframe and the status chip and the note under it are plain text set
 * from code. None of the three were ever redrawn, so a Persian user who opened
 * Quick Export was told "Choose a source file to see a preview." in English
 * for the rest of the session. Remembering what was drawn is what makes
 * redrawing it possible. */
let exportPreviewStateKey = "";
let exportPreviewNotePayload = null;

function setExportPreviewState(key) {
  exportPreviewStateKey = key || "";
  const label = $("#export-preview-state");
  if (label) label.textContent = key ? t(key) : "";
}

/** Put the export preview back into the interface language. */
function retranslateExportPreview() {
  setExportPreviewState(exportPreviewStateKey);
  renderPreviewNote(exportPreviewNotePayload);
  if (!pageDeck) return;
  // With no source there is nothing to ask the engine for; with one, the
  // sheet itself carries translated furniture and has to be drawn again.
  if (!state.sourcePath) pageDeck.showMessage(t("previewChooseSource"));
  else schedulePdfPreview(0);
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
 * A note under the preview for the things it cannot show.
 *
 * An older engine can only supply body HTML; in that case the page furniture
 * is assumed rather than measured. Math is rendered locally in every preview.
 */
function renderPreviewNote(payload) {
  exportPreviewNotePayload = payload || null;
  const note = $("#export-preview-note");
  if (!note) return;
  const lines = [];
  if (payload?.degraded) lines.push(t("previewEngineOutdated"));
  note.classList.toggle("hidden", lines.length === 0);
  note.textContent = lines.join(" · ");
}

/**
 * Build a page payload from the body-only preview an older engine can give.
 *
 * `preview.document_page` was added with this screen. A desktop build carries a
 * compiled engine, so a rebuilt interface on an unrebuilt runtime is a normal
 * state — and answering it with the raw string "Unknown method:
 * preview.document_page" in the preview panel is not. The appearance the older
 * method does return is real; only the sheet geometry is assumed, and the note
 * says so.
 */
function pagePayloadFromBodyPreview(result) {
  const appearance = result?.appearance || {};
  return {
    degraded: true,
    title: result?.title || "",
    lang: "",
    direction: "",
    page: {},
    css: {
      fonts: "",
      pygments: result?.pygments_css || "",
      style: appearance.style_css || "",
      palette: appearance.palette_css || "",
      layout: "",
    },
    body_classes: appearance.body_classes || "",
    content_html: [
      result?.toc_html || "",
      result?.reference_lists_html || "",
      result?.body_html || "",
      result?.bibliography_html || "",
    ].join(""),
    watermark_html: "",
    cover: null,
    footer: { enabled: false, html: "" },
    math: { typeset_at_export: true, expressions: 0 },
  };
}

/**
 * Draw the preview, one at a time.
 *
 * Composing the page is Markdown work the engine cannot interrupt, and on a
 * long document it takes seconds. Sending the next preview while that one is
 * still running earns SERVER_BUSY and puts "Preview unavailable" on screen over
 * a document with nothing wrong with it — and the longer the document, the more
 * reliably it happened. Only the newest options matter, so a request that
 * arrives mid-render is remembered rather than sent, and runs once the engine
 * is free.
 */
function renderExportPreview() {
  return exportPreviewFlight.run();
}

async function drawExportPreview() {
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
    const request = { path: state.sourcePath, content, options: exportOverrides(), requestId: id };
    const result = engineSupports("preview.document_page")
      ? await previewDocumentPage(request)
      : pagePayloadFromBodyPreview(await previewDocumentText(request));
    if (sequence !== exportPreviewSequence) return;
    deck.render(result);
    renderPreviewNote(result);
    setExportPreviewState("");
  } catch (error) {
    if (sequence !== exportPreviewSequence) return;
    setExportPreviewState("previewFailedShort");
    const payload = errorPayload(error);
    renderPreviewNote(null);
    deck.showMessage(payload?.message || t("previewFailed"), diagnosticLines(payload));
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
    button.innerHTML = `<strong></strong><small></small><i aria-hidden="true"></i>`;
    button.querySelector("i").append(spriteIcon("check"));
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
    setTruncatableText(detail, value);
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
    button.innerHTML = `<span>MD</span><div class="recent-copy"><strong></strong><small></small></div><b class="recent-arrow" aria-hidden="true"></b>`;
    button.querySelector(".recent-arrow").append(spriteIcon("chevron-left"));
    setTruncatableText(button.querySelector("strong"), basename(recent.path));
    setTruncatableText(button.querySelector("small"), recent.path);
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
  setTruncatableText($("#export-result-name"), basename(resultPath));
  setTruncatableText($("#export-result-path"), resultPath);
  container.classList.remove("hidden");
}

function openExportSource(path) {
  state.exportReturnView = $("#workspace-view").classList.contains("active") ? "workspace" : "start";
  hideExportResult();
  state.sourcePath = path;
  state.outputPath = defaultOutputPath(path);
  $("#source-path").value = path;
  $("#output-path").value = state.outputPath;
  setExportStatus("idle", "readyTitle", t("readyMessage"));
  showView("export");
  // The document is the preview's only subject. Without this the panel stayed
  // on "choose a source file" until some unrelated option was touched, which
  // is the one moment the user is least expecting to have to.
  schedulePdfPreview(120);
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
  if (state.activeRequestId || !exportSelectionValid()) return;
  const id = requestId("validate");
  const params = buildDocumentParams({ sourcePath: state.sourcePath, outputPath: state.outputPath, presetId: state.presetId, overrides: exportOverrides() });
  state.activeRequestId = id;
  state.cancelledExportRequestId = null;
  working(true, "validate");
  try {
    await releaseEngineForJob();
    if (state.cancelledExportRequestId === id) {
      setExportStatus("idle", "readyTitle", t("operationCancelled"));
      return;
    }
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
  if (state.activeRequestId || !exportSelectionValid()) return;
  const id = requestId("render");
  const params = buildDocumentParams({ sourcePath: state.sourcePath, outputPath: state.outputPath, presetId: state.presetId, overrides: exportOverrides() });
  state.activeRequestId = id;
  state.cancelledExportRequestId = null;
  working(true);
  hideExportResult();
  try {
    await releaseEngineForJob();
    if (state.cancelledExportRequestId === id) {
      setExportStatus("idle", "readyTitle", t("operationCancelled"));
      return;
    }
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
  state.cancelledExportRequestId = state.activeRequestId;
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
  tab.innerHTML = `<button class="tab-activate" type="button" role="tab"><i class="dirty-dot"></i><span class="tab-name"></span></button><button class="tab-close" type="button" aria-label="${t("close")}"></button>`;
  tab.querySelector(".tab-close").append(spriteIcon("close"));
  setTruncatableText(tab.querySelector(".tab-name"), model.title);
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
    const rtl = document.documentElement.dir === "rtl";
    if (event.key === (rtl ? "ArrowRight" : "ArrowLeft") || event.key === "ArrowUp") target = state.documents[(index - 1 + state.documents.length) % state.documents.length];
    if (event.key === (rtl ? "ArrowLeft" : "ArrowRight") || event.key === "ArrowDown") target = state.documents[(index + 1) % state.documents.length];
    if (event.key === "Home") target = state.documents[0];
    if (event.key === "End") target = state.documents.at(-1);
    if (!target) return;
    event.preventDefault();
    void activateDocument(target.id, { focus: "tab" });
  });
  tab.querySelector(".tab-close").addEventListener("click", (event) => {
    event.stopPropagation();
    void requestCloseDocument(model.id);
  });
  return tab;
}

function renderDocumentTabs() {
  const container = $("#document-tabs");
  if (!container) return;
  container.replaceChildren(...state.documents.map(tabElement));
  renderFileNavigator();
}

function renderFileNavigator() {
  const list = $("#open-document-list");
  if (!list) return;
  list.replaceChildren();
  for (const model of state.documents) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `navigator-document${model.id === state.activeDocumentId ? " active" : ""}${documentDirty(model) ? " dirty" : ""}`;
    button.dataset.documentId = model.id;
    button.setAttribute("aria-current", model.id === state.activeDocumentId ? "page" : "false");
    button.innerHTML = '<i aria-hidden="true"></i><span><strong></strong><small dir="auto"></small></span>';
    button.querySelector("i").append(spriteIcon("file"));
    button.querySelector("strong").textContent = model.title;
    button.querySelector("small").textContent = model.path || t("unsavedDocument");
    button.title = `${model.title}\n${model.path || t("unsavedDocument")}${documentDirty(model) ? `\n${t("unsaved")}` : ""}`;
    button.setAttribute("aria-label", button.title);
    button.addEventListener("click", async () => {
      await activateDocument(model.id);
      if (matchMedia("(max-width: 1100px)").matches) {
        state.workspaceLayout.filesOpen = false;
        applyWorkspaceLayout();
      }
    });
    list.append(button);
  }
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
  const model = activeDocument();
  const position = editorAdapter?.lineAtOffset?.() || textMetrics(model?.content || "", currentEditor().selectionStart);
  const metrics = documentMetrics(model, position);
  $("#cursor-status").textContent = `${t("lineShort")} ${metrics.line}, ${t("columnShort")} ${metrics.column}`;
  $("#word-status").textContent = `${metrics.words} ${t("wordsLabel")} · ${metrics.characters} ${t("charactersLabel")}`;
  outlineNavigator?.setActiveLine(metrics.line, { scroll: true });
  updateFormattingState();
}

function updateFormattingState() {
  const flags = editorAdapter?.getFormattingState?.() || {};
  for (const button of $$('[data-editor-command]')) {
    const command = button.dataset.editorCommand;
    if (Object.hasOwn(flags, command) && typeof flags[command] === "boolean") button.setAttribute("aria-pressed", String(flags[command]));
    else button.removeAttribute("aria-pressed");
  }
}

function renderOutline(model) {
  const outline = extractOutline(model?.content || "");
  $("#outline-count").textContent = String(outline.length);
  if (!outlineNavigator) outlineNavigator = createOutlineNavigator({ container: $("#outline-list"), onNavigate: (line) => goToLine(line) });
  if (outlineLocale !== state.locale) {
    outlineLocale = state.locale;
    outlineNavigator.setLabels({ empty: t("noOutline"), noMatches: t("noOutlineMatches"), label: t("documentOutline"), expand: t("expandOutline"), collapse: t("collapseOutline") });
  }
  outlineNavigator.setItems(outline, { documentId: model?.id || "empty" });
  applyNavigatorContext();
}

const frontMatterFormBaseline = new Map();

function loadFrontMatterForm(model) {
  const form = $("#frontmatter-form");
  const { fields, rawLines } = parseFrontMatter(model?.content || "");
  frontMatterFormBaseline.clear();
  let hasStructuredFields = false;
  for (const name of ["title", "subtitle", "author", "lang", "dir"]) {
    const input = form.elements.namedItem(name);
    if (!input) continue;
    const value = fields[name];
    const present = rawLines.some((line) => new RegExp(`^(?:${name}|"${name}"|'${name}'):`).test(line));
    const structured = present && (value === undefined || (value !== null && typeof value === "object")
      || /[\r\n]/.test(String(value ?? ""))
      || (input instanceof HTMLSelectElement && value !== undefined && ![...input.options].some((option) => option.value === String(value))));
    input.value = structured ? "" : value ?? (name === "lang" || name === "dir" ? "auto" : "");
    input.disabled = !documentEditable() || structured;
    input.title = structured ? t("structuredMetadataHelp") : "";
    frontMatterFormBaseline.set(name, input.value);
    hasStructuredFields ||= structured;
  }
  const toc = form.elements.namedItem("toc");
  const tocPresent = rawLines.some((line) => /^(?:toc|"toc"|'toc'):/.test(line));
  const tocStructured = tocPresent && typeof fields.toc !== "boolean";
  toc.checked = fields.toc === true;
  toc.disabled = !documentEditable() || tocStructured;
  toc.title = tocStructured ? t("structuredMetadataHelp") : "";
  frontMatterFormBaseline.set("toc", toc.checked);
  $("#structured-metadata-note")?.classList.toggle("hidden", !(hasStructuredFields || tocStructured));
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
    button.querySelector("small").textContent = t(used.includes(key) ? "cited" : "bibliographyLibrary");
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
    const pending = isMarkdownModel(model) && model?.validationContentVersion !== model?.contentVersion
      && model?.previewContentVersion !== model?.contentVersion;
    const note = document.createElement("div");
    note.className = "tool-empty";
    note.textContent = t(pending ? "contentChecksPending" : "noProblems");
    list.append(note);
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
  editorAdapter?.setAriaLabel?.(t(markdown ? "markdownEditor" : "textResourceEditor"));
  const editable = hasDocument && !model.readOnly && !state.updateInstalling && !state.bookPreparing && effectiveViewMode() !== "read";
  $("#workspace-save").disabled = !hasDocument || model.readOnly;
  $("#workspace-save-as").disabled = !hasDocument;
  for (const element of $$('[data-editor-command], #workspace-import-asset, #import-asset, #refresh-assets')) {
    element.disabled = !editable || !markdown;
  }
  for (const selector of ["#workspace-validate", "#workspace-export", "#refresh-preview", "#auto-preview", "#refresh-reading", "#reading-auto-preview"]) {
    $(selector).disabled = !hasDocument || !markdown;
  }
  for (const name of ["outline", "frontmatter", "assets", "citations"]) {
    const button = $(`[data-sidebar="${name}"]`);
    if (button) button.disabled = !hasDocument || !markdown;
  }
  applySidebarContext();
  $("#frontmatter-form")?.querySelectorAll("input,select,button").forEach((element) => {
    element.disabled = !editable || !markdown;
  });
  $("#workspace-view")?.classList.toggle("plain-text-mode", hasDocument && !markdown);
  $("#insert-menu-button").disabled = !editable || !markdown;
  $("#workspace-toggle-formatting")?.toggleAttribute("disabled", !editable || !markdown);
  editorAdapter?.setReadOnly?.(Boolean(model?.readOnly) || effectiveViewMode() === "read" || state.updateInstalling || Boolean(state.bookPreparing));
}

/**
 * A date the reader of this interface can read.
 *
 * `toLocaleString()` with no argument formats for the machine's locale, so a
 * Persian interface on an English system said "11/15/2023, 1:43:20 AM" — the
 * one piece of text in the recovery dialog that never followed the language
 * the rest of it was in. Naming the interface's own locale gives the Persian
 * calendar and Persian digits where the interface is Persian.
 */
function formatMoment(value) {
  const moment = new Date(Number(value) || Date.now());
  const locale = state.locale === "fa" ? "fa-IR" : "en-GB";
  try {
    return moment.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return moment.toISOString().slice(0, 16).replace("T", " ");
  }
}

/**
 * The little text the editor draws itself.
 *
 * The bundled editor has no access to the interface's dictionary, so the label
 * on an image it could not load was English in a Persian document. The host
 * owns the words; the editor owns the drawing.
 */
function editorStrings() {
  return { imageNotFound: t("imageNotFound"), remoteImageNotLoaded: t("remoteImageNotLoaded") };
}

/**
 * Ask the user to confirm something, in this application's own dialog.
 *
 * The three decisions that most deserve a considered answer — overwrite a file
 * that changed on disk, close a document with unsaved work, drop a chapter
 * from a book — were asked with `window.confirm`. That draws the platform's
 * dialog: another typeface, another button order, another focus model, a title
 * bar naming the webview, and nothing translated past the string it is handed.
 * On the one screen where the product's whole claim is that it will not
 * overwrite your file without asking, the asking was done by something that
 * did not look like the product.
 *
 * Cancel is what focus lands on and what every way out resolves to, because
 * every one of these questions has a destructive answer and a safe one.
 */
function presentConfirmation({ title, message = "", confirmLabel, danger = false }) {
  const modal = $("#confirm-modal");
  const accept = $("#confirm-accept");
  const cancel = $("#confirm-cancel");
  if (!modal || !accept || !cancel) return Promise.resolve(false);
  $("#confirm-title").textContent = String(title || "");
  $("#confirm-message").textContent = String(message || "");
  accept.textContent = String(confirmLabel || t("confirm"));
  accept.classList.toggle("danger", Boolean(danger));
  accept.classList.toggle("primary", !danger);
  return new Promise((resolve) => {
    let answer = false;
    const finish = (value) => {
      answer = value;
      modalManager.close(modal);
    };
    const onAccept = () => finish(true);
    const onCancel = () => finish(false);
    accept.addEventListener("click", onAccept);
    cancel.addEventListener("click", onCancel);
    modalManager.open(modal, {
      initialFocus: "#confirm-cancel",
      onClose: () => {
        accept.removeEventListener("click", onAccept);
        cancel.removeEventListener("click", onCancel);
        resolve(answer);
      },
    });
  });
}

/**
 * Write a label that may be wider than the box it is written into.
 *
 * Eighteen places in the workbench truncate with `text-overflow: ellipsis`,
 * and most of them hold a value the user needs whole: the path of the open
 * document, a chapter's file, a citation's title, a search hit's line. An
 * ellipsis with nothing behind it is a value that cannot be got at. The whole
 * string goes on the element's own `title`, which is where a pointer looks
 * and what a screen reader reads after the visible text.
 */
function setTruncatableText(element, value) {
  if (!element) return;
  const text = String(value ?? "");
  element.textContent = text;
  if (text) element.title = text;
  else element.removeAttribute("title");
}

function renderWorkspace() {
  const model = activeDocument();
  renderDocumentTabs();
  const editor = currentEditor();
  editor.retainDocuments?.(state.documents.map((document) => document.id));
  renderProjectWorkspace();
  renderBookWorkspace();
  if (!model) {
    if (editor.setDocument) editor.setDocument(null, "");
    else editor.value = "";
    editor.disabled = true;
    setTruncatableText($("#editor-title"), t("untitled"));
    setTruncatableText($("#editor-path"), "");
    renderOutline(null);
    renderCitations(null);
    renderProblems(null);
    updateAuthoringMode(null);
    applyViewMode();
    renderPreviewMessage(t("previewEmpty"));
    return;
  }
  editor.disabled = model.readOnly;
  updateAuthoringMode(model);
  // The adapter owns each document's undo history, selection and scroll.
  // Initial selection is applied only when the adapter sees this ID first.
  if (editor.setDocument) editor.setDocument(model.id, model.content, { initialSelection: bodyStartOffset(model.content), kind: isMarkdownModel(model) ? "markdown" : "text" });
  else if (editor.value !== model.content) editor.value = model.content;
  if (!$("#find-bar").classList.contains("hidden")) updateFindMatches();
  setTruncatableText($("#editor-title"), model.title);
  setTruncatableText($("#editor-path"), model.path || t("untitled"));
  setSaveState(documentDirty(model) ? "dirty" : "saved");
  updateLineGutter();
  updateEditorMetrics();
  renderOutline(isMarkdownModel(model) ? model : null);
  if (isMarkdownModel(model)) loadFrontMatterForm(model);
  renderCitations(isMarkdownModel(model) ? model : null);
  renderProblems(model);
  applyViewMode();
  renderPreview(model);
}

/**
 * Let the webview read images from a document's own directory.
 *
 * Grant the native scope's bounded set of local images before widgets load.
 */
async function allowDocumentImages(model) {
  if (!model?.path) return;
  const path = model.path;
  const sources = documentImageSources(model.content);
  try {
    await invoke("allow_document_images", { path, sources });
    if (model.path === path) {
      documentImageScopes.set(model, { path, sources: new Set(sources) });
      if (activeDocument() === model) editorAdapter?.refreshAssets?.();
    }
  } catch {
    // Images stay as Markdown text; nothing else about the document changes.
  }
}

function scheduleDocumentImages(model) {
  clearTimeout(imageScopeTimer);
  if (!model?.path) return;
  imageScopeTimer = setTimeout(() => {
    if (!state.documents.includes(model)) return;
    const granted = documentImageScopes.get(model);
    const sources = documentImageSources(model.content);
    if (granted?.path === model.path && sources.length === granted.sources.size
      && sources.every((source) => granted.sources.has(source))) return;
    void allowDocumentImages(model);
  }, 220);
}

async function activateDocument(id, { focus = "editor" } = {}) {
  const model = state.documents.find((document) => document.id === id);
  if (!model) return;
  const sequence = ++state.documentActivationSequence;
  await allowDocumentImages(model);
  if (sequence !== state.documentActivationSequence || !state.documents.includes(model)) return;
  state.activeDocumentId = id;
  state.validationSequence += 1;
  state.assetSequence += 1;
  state.bibliographySequence += 1;
  persistSession();
  renderWorkspace();
  if (focus === "tab") {
    const tab = $$(".document-tab").find((element) => element.dataset.documentId === id);
    tab?.querySelector(".tab-activate")?.focus({ preventScroll: true });
  } else if (effectiveViewMode() === "read") $("#reading-document")?.focus({ preventScroll: true });
  else currentEditor().focus();
  schedulePreview(80, { entering: true });
  if (model.path) refreshAssets();
}

function createUntitledDocument() {
  state.documentActivationSequence += 1;
  if (state.preferences.viewMode === "read") updatePreference({ viewMode: "write" });
  const model = createDocument({ content: "" });
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
  const sequence = ++state.documentActivationSequence;
  let intendedDocument = null;
  showView("workspace");
  for (const path of values) {
    const existing = findDocumentByPath(state.documents, path);
    if (existing) {
      await allowDocumentImages(existing);
      if (state.documents.includes(existing)) intendedDocument = existing;
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
      await allowDocumentImages(model);
      if (state.documents.includes(model)) intendedDocument = model;
      saveRecent(model.path);
      const recovery = recoveryForPath(model.path);
      if (sequence === state.documentActivationSequence && state.documents.includes(model)
          && recovery && recovery.content !== model.content) showRecovery(model, recovery);
    } catch (error) {
      toast(errorText(error), "error");
    }
  }
  // Keep the owner of the visible buffer unchanged throughout every file read
  // and scope grant, including when several files are opened together.
  if (sequence === state.documentActivationSequence && state.documents.includes(intendedDocument)) {
    state.activeDocumentId = intendedDocument.id;
    state.validationSequence += 1;
    state.assetSequence += 1;
    state.bibliographySequence += 1;
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
  const activationSequence = ++state.documentActivationSequence;
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
  if (activationSequence !== state.documentActivationSequence) return payload;
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
  renderFileNavigator();
  const empty = $("#project-empty");
  const tools = $("#project-tools");
  const list = $("#project-file-tree");
  const section = $("#navigator-project-section");
  const defaults = $("#project-open-settings");
  if (!empty || !tools || !list || !section) return;
  const project = state.project;
  empty.classList.toggle("hidden", Boolean(project));
  tools.classList.toggle("hidden", !project);
  section.classList.toggle("hidden", !project);
  list.replaceChildren();
  if (defaults) {
    defaults.disabled = !project?.config;
    defaults.onclick = project?.config ? () => openProjectRelativeFile(project.config) : null;
  }
  if (!project) {
    setTruncatableText($("#navigator-project-name"), "");
    $("#project-search-results")?.replaceChildren();
    return;
  }
  setTruncatableText($("#navigator-project-name"), project.name || t("projectWorkspace"));
  setTruncatableText($("#project-name"), project.name || t("projectWorkspace"));
  setTruncatableText($("#project-path"), project.path || "");
  const files = Array.isArray(project.files) ? project.files : [];
  for (const file of files) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tool-item navigator-project-file";
    button.dataset.kind = file.kind || "text";
    button.dataset.projectPath = file.path;
    button.innerHTML = `<span></span>`;
    button.querySelector("span").textContent = file.chapter_title
      ? `${file.chapter_title} — ${file.path}`
      : file.path;
    button.title = file.path;
    button.dir = "auto";
    const current = activeDocument();
    const selected = current?.projectPath === project.path && current?.projectRelativePath === file.path;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-current", selected ? "page" : "false");
    if (["markdown", "text", "config", "toml", "bibliography", "json"].includes(file.kind)) {
      button.addEventListener("click", async () => {
        await openProjectRelativeFile(file.path);
        if (matchMedia("(max-width: 1100px)").matches) {
          state.workspaceLayout.filesOpen = false;
          applyWorkspaceLayout();
        }
      });
    } else {
      button.disabled = true;
      button.title = `${file.path}\n${t("unsupportedProjectFile")}`;
    }
    list.append(button);
  }
}

async function openProjectRelativeFile(relativePath, { line = null, column = 1 } = {}) {
  const projectPath = state.project?.path;
  const projectGeneration = state.projectGeneration;
  if (!projectPath) return;
  const sequence = ++state.documentActivationSequence;
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
    if (sequence !== state.documentActivationSequence) return;
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
    }
    await allowDocumentImages(model);
    if (sequence !== state.documentActivationSequence || !state.documents.includes(model)
        || state.project?.path !== projectPath || state.projectGeneration !== projectGeneration) return;
    // Recheck unsaved edits after the asynchronous grant. An existing document
    // may still be visible and editable while this request is pending.
    if (existing && result.content !== model.savedContent) {
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
  }
  for (const match of matches) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tool-item";
    button.innerHTML = `<span class="match-location"></span><span class="match-preview"></span>`;
    button.querySelector(".match-location").textContent = `${match.path}:${match.line}:${match.column}`;
    setTruncatableText(button.querySelector(".match-preview"), match.preview || "");
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
  if (Number(result?.truncated_lines) > 0) {
    const notice = document.createElement("div");
    notice.className = "tool-empty search-limit-notice";
    notice.textContent = `${t("regexLongLineLimit")} ${result.regex_line_limit || 2000} · ${t("regexLimitedLines")}: ${result.truncated_lines}. ${t("useLiteralSearch")}`;
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
  state.bookPreparing = false;
  updateAuthoringMode(activeDocument());
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
  beforePrepare = null,
} = {}) {
  const projectPath = state.project?.path;
  const projectIdentity = pathKey(projectPath);
  let projectContext = currentProjectContext();
  // Claim before any picker, confirmation or save can yield to another click.
  const task = claimBookTask(state, () => ({
    requestId: null,
    promise: Promise.resolve().then(async () => {
      const isCurrent = () => sequence === state.bookRequestSequence
        && pathKey(state.project?.path) === projectIdentity;
      if (!projectIdentity || !isCurrent()) return null;
      if (beforePrepare && !await beforePrepare()) return null;
      const prepared = await prepareBookFiles({
        projectPath, getDocuments: () => state.documents, isDirty: documentDirty, isCurrent,
        confirm: () => askConfirmation({
          title: t("bookSaveChangesTitle"), message: t("bookSaveChangesHelp"),
          confirmLabel: t("bookSaveAndContinue"),
        }),
        save: (model) => saveCoordinator.save(model,
          () => persistDocumentModel(model, { refreshProjectOnSave: false })),
      });
      if (!prepared || !isCurrent()) return null;
      // mardas.toml can change chapter order or bibliography settings. Refresh
      // once after every open project input has reached disk.
      const refreshed = await refreshProject(projectPath);
      if (!isCurrent()) return null;
      applyProjectPayload(refreshed);
      projectContext = currentProjectContext();
      const started = startTask();
      state.activeBookRequestId = started.requestId || null;
      setBookOperationStatus(t("bookOperationRunning"), { running: true });
      state.bookPreparing = false;
      updateAuthoringMode(activeDocument());
      return started.promise;
    }),
  }));
  if (!task) {
    toast(t("bookOperationAlreadyRunning"), "warning");
    syncBookOperationControls();
    return null;
  }
  const sequence = ++state.bookRequestSequence;
  const taskPromise = task.promise;
  state.bookPreparing = true;
  updateAuthoringMode(activeDocument());
  setBookOperationStatus(t("bookOperationRunning"));
  try {
    const result = await taskPromise;
    if (!result) {
      if (sequence === state.bookRequestSequence) setBookOperationStatus("");
      return null;
    }
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
      state.bookPreparing = false;
      updateAuthoringMode(activeDocument());
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
  const confirmed = await askConfirmation({
    title: t("removeFromBook"),
    message: t("confirmRemoveChapter"),
    confirmLabel: t("removeFromBook"),
    danger: true,
  });
  if (!confirmed) return;
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
    <span class="book-chapter-handle" aria-hidden="true"></span>
    <button class="book-chapter-main" type="button"><strong></strong><small></small></button>
    <span class="book-chapter-actions">
      <button type="button" data-action="up"></button>
      <button type="button" data-action="down"></button>
      <button type="button" data-action="duplicate"></button>
      <button class="danger" type="button" data-action="remove"></button>
    </span>`;
  row.querySelector(".book-chapter-handle").append(spriteIcon("grip"));
  for (const [action, symbol] of Object.entries({
    up: "chevron-up", down: "chevron-down", duplicate: "duplicate", remove: "close",
  })) {
    row.querySelector(`[data-action="${action}"]`).append(spriteIcon(symbol));
  }
  const chapterLabel = `${index + 1}. ${chapter.title || chapter.path}`;
  setTruncatableText(row.querySelector("strong"), chapterLabel);
  setTruncatableText(row.querySelector("small"), chapter.path);
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
  setTruncatableText($("#book-output-result-name"), basename(path));
  setTruncatableText($("#book-output-result-path"), path);
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
  const content = (parsed.querySelector(".md2pdf-article") || parsed.body).cloneNode(true);
  // This is a review of the saved chapters, not the publication layout. Keep
  // the ordered contents/references while leaving cover and watermark in PDF.
  content.querySelectorAll(":scope > .md2pdf-cover, :scope > .md2pdf-watermark")
    .forEach((element) => element.remove());
  const dialog = $("#book-review-modal");
  const container = $("#book-review-document");
  const token = requestId("book-review");
  container.dataset.reviewToken = token;
  container.dir = parsed.body.getAttribute("dir") || parsed.documentElement.getAttribute("dir") || "auto";
  container.lang = parsed.documentElement.lang || "";
  container.replaceChildren();
  // Full renderer styles target html/body and must never escape into the desktop
  // shell. Whole-book review does not replace the active chapter's comparison
  // pane or change its editing mode.
  container.append(safePreviewHtml(content.innerHTML, "book-review-"));
  $("#book-review-project").textContent = bookProject()?.title || state.project?.name || t("bookProject");
  $("#close-book-review").onclick = () => modalManager.close(dialog);
  $("#book-review-done").onclick = () => modalManager.close(dialog);
  modalManager.open(dialog, {
    initialFocus: "#close-book-review",
    returnFocus: $("#book-preview"),
    onClose: () => { container.replaceChildren(); delete container.dataset.reviewToken; },
  });
  void typesetPreviewMath(container, {
    isCurrent: () => container.dataset.reviewToken === token && modalManager.isOpen(dialog),
    errorLabel: t("previewMathFailed"),
  });
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
  await runBookTask(() => startBookExport({
    projectPath: project.path,
    outputPath,
  }), {
    beforePrepare: async () => {
      outputPath = await invoke("pick_pdf_output", {
        suggested_path: `${project.path}/${book.output || "dist/book.pdf"}`,
      });
      return Boolean(outputPath);
    },
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
    setTruncatableText(row.querySelector("strong"), entry.title || key);
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
  $("#recovery-message").textContent = `${t("recoveryMessage")} ${formatMoment(recovery.updatedAt)}`;
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

async function persistDocumentModel(model, { saveAs = false, force = false, refreshProjectOnSave = true } = {}) {
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
    if (refreshProjectOnSave && isProjectSave && model.projectRelativePath === "mardas.toml") {
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
      const overwrite = await askConfirmation({
        title: t("externalChange"),
        message: t("documentConflict"),
        confirmLabel: t("forceSave"),
        danger: true,
      });
      if (overwrite) return persistDocumentModel(model, { saveAs: false, force: true, refreshProjectOnSave });
      return false;
    }
    if (activeDocument()?.id === model.id) {
      setSaveState("dirty");
      toast(errorText(error), "error");
    }
    return false;
  }
}

async function requestCloseDocument(id) {
  const model = state.documents.find((document) => document.id === id);
  if (!model) return;
  state.documentActivationSequence += 1;
  if (documentDirty(model)) {
    const discard = await askConfirmation({
      title: model.title,
      message: t("closeUnsavedHelp"),
      confirmLabel: t("closeWithoutSaving"),
      danger: true,
    });
    if (!discard) return;
  }
  if (!state.documents.includes(model)) return;
  cancelRecoveryTimer(model);
  removeRecovery(model);
  const result = closeDocument(state.documents, id);
  const wasActive = state.activeDocumentId === id;
  state.documents = result.documents;
  if (wasActive) state.activeDocumentId = null;
  persistSession();
  renderWorkspace();
  if (!state.documents.length) showView("start");
  else if (wasActive) await activateDocument(result.nextId);
}

function onEditorInput() {
  const model = activeDocument();
  if (!model) return;
  updateDocumentContent(model, currentEditor().value);
  scheduleDocumentImages(model);
  if (!$("#find-bar").classList.contains("hidden")) updateFindMatches();
  state.validationSequence += 1;
  state.bibliographySequence += 1;
  model.diagnostics = [];
  model.bibliographyDiagnostics = [];
  renderProblems(model);
  setSaveState(documentDirty(model) ? "dirty" : "saved");
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

function renderContentStatus() {
  const model = activeDocument();
  const stale = Boolean(model?.preview && model.previewContentVersion !== model.contentVersion);
  const label = stale ? t("contentPreviewStale") : !state.preferences.autoPreview
    ? t("contentPreviewPaused") : t("contentPreviewScope");
  for (const status of $$('[data-content-status]')) {
    status.textContent = label;
    status.dataset.stale = String(stale);
    status.title = t("previewScope");
  }
}

function schedulePreview(delay = 650, { entering = false } = {}) {
  // Retire whatever is on screen or in flight: its result is already stale.
  state.previewSequence += 1;
  clearTimeout(state.previewTimer);
  const model = activeDocument();
  renderContentStatus();
  if (!contentViewVisible()) return;
  if (!model || !isMarkdownModel(model) || !model.content.trim()) {
    if (model) model.preview = null;
    renderPreview(model);
    $("#preview-loading")?.classList.add("hidden");
    $("#reading-loading")?.classList.add("hidden");
    return;
  }
  // Opening a content view is an explicit request for the current document.
  // Pausing only stops subsequent typing updates in either visible surface.
  if (!state.preferences.autoPreview && !entering && model.preview) {
    $("#preview-loading")?.classList.add("hidden");
    $("#reading-loading")?.classList.add("hidden");
    return;
  }
  renderPreview(model);
  state.previewTimer = setTimeout(() => void refreshPreview(), delay);
}

function previewOptions() {
  // The engine already applies project configuration and the buffer's front matter.
  // Keeping request overrides sparse preserves that documented precedence.
  return {};
}

function safePreviewHtml(value, prefix = "preview-") {
  const template = document.createElement("template");
  template.innerHTML = String(value || "");
  template.content
    .querySelectorAll("script,style,iframe,object,embed,meta,base,link,form,button,select,option,textarea")
    .forEach((element) => element.remove());
  const idMap = new Map();
  template.content.querySelectorAll("[id]").forEach((element) => {
    const original = element.id;
    const prefixed = `${prefix}${original}`;
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
          element.setAttribute("href", `#${idMap.get(target) || `${prefix}${target}`}`);
        } else {
          element.removeAttribute("href");
          element.setAttribute("aria-disabled", "true");
          continue;
        }
      }
      if (name === "src" && !/^\s*data:image\//i.test(attribute.value)) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (["for", "aria-labelledby", "aria-describedby"].includes(name)) {
        const rewritten = attribute.value
          .split(/\s+/)
          .map((id) => idMap.get(id) || `${prefix}${id}`)
          .join(" ");
        element.setAttribute(attribute.name, rewritten);
      }
      // Prefixing ids also has to prefix what points at them. A Mermaid
      // arrowhead is a `<marker id=…>` referenced by `marker-end="url(#…)"`,
      // so rewriting one without the other left every diagram without arrows.
      if (["marker-start", "marker-mid", "marker-end", "clip-path", "mask", "fill", "stroke", "filter"].includes(name)
        && /url\s*\(/i.test(attribute.value)) {
        const localReference = /url\(\s*["']?#([^\s)"']+)["']?\s*\)/g;
        if (/url\s*\(/i.test(attribute.value.replace(localReference, ""))) {
          element.removeAttribute(attribute.name);
          continue;
        }
        element.setAttribute(
          attribute.name,
          attribute.value.replace(
            localReference,
            (whole, id) => `url(#${idMap.get(id) || `${prefix}${id}`})`,
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
  $("#reading-document")?.replaceChildren(message.cloneNode(true));
}

const readingScroll = new Map();
let readingDocumentId = null;

let pendingReadingLine = null;

function contentAnchors(container, model) {
  const frame = container.getBoundingClientRect();
  const anchors = [{ line: 1, top: 0 }];
  for (const heading of container.querySelectorAll("h1[data-source-line],h2[data-source-line],h3[data-source-line],h4[data-source-line],h5[data-source-line],h6[data-source-line]")) {
    const line = Number(heading.dataset.sourceLine);
    if (line > anchors.at(-1).line) anchors.push({ line, top: heading.getBoundingClientRect().top - frame.top + container.scrollTop });
  }
  anchors.push({ line: model.content.split("\n").length + 1, top: container.scrollHeight });
  return anchors;
}

function readingSourceLine() {
  const container = $("#reading-document");
  const model = activeDocument();
  return model && container ? Math.round(interpolatePosition(contentAnchors(container, model), container.scrollTop, "top", "line")) : 1;
}

function renderReading(model) {
  if (effectiveViewMode() !== "read") return;
  const container = $("#reading-document");
  if (!container) return;
  if (readingDocumentId !== model?.id) {
    readingDocumentId = model?.id || null;
    for (const id of readingScroll.keys()) {
      if (!state.documents.some((item) => item.id === id)) readingScroll.delete(id);
    }
    container.scrollTop = readingScroll.get(readingDocumentId) || 0;
  }
  if (!model?.preview) {
    container.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "empty-preview";
    empty.textContent = model?.content.trim() ? t("renderingPreview") : t("previewEmpty");
    container.append(empty);
    return;
  }
  const previousScroll = readingScroll.get(model.id) ?? container.scrollTop;
  const payload = model.preview;
  mountDocumentContent(container, payload, {
    sanitize: safePreviewHtml, prefix: "reading-", sourceEntries: previewSourceEntries(model),
    blockedImageLabel: (reason) => t(reason === "remote" ? "remoteImageNotLoaded" : "imageBlockedOrMissing"),
  });
  container.scrollTop = previousScroll;
  const current = () => activeDocument()?.id === model.id && model.preview === payload;
  return typesetPreviewMath(container, { isCurrent: current, errorLabel: t("previewMathFailed") }).then(() => {
    if (current() && pendingReadingLine?.id === model.id) {
      container.scrollTop = interpolatePosition(contentAnchors(container, model), pendingReadingLine.line);
      pendingReadingLine = null;
    }
  });
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
  // Wrapped rows and Markdown widgets do not correspond one-for-one with
  // source lines. The textarea fallback has no measured document map.
  const lineHeight = Number.parseFloat(getComputedStyle(editorElement).lineHeight) || 24;
  const visibleLine = editorAdapter?.firstVisibleLine?.()
    ?? Math.max(1, Math.floor((Number(scrollTop) || 0) / lineHeight) + 1);
  syncPreviewToEditorLine(visibleLine);
}

function renderPreview(model) {
  renderContentStatus();
  if (effectiveViewMode() === "read") return renderReading(model);
  if (!contentViewVisible()) return;
  const container = $("#preview-document");
  if (!model?.preview) {
    renderPreviewMessage(t("previewEmpty"));
    return;
  }
  const payload = model.preview;
  mountDocumentContent(container, payload, {
    sanitize: safePreviewHtml, sourceEntries: previewSourceEntries(model),
    onSourceJump: (line) => goToLine(line),
    sourceJumpLabel: (line) => `${t("goToSourceLine")} ${line}`,
    blockedImageLabel: (reason) => t(reason === "remote" ? "remoteImageNotLoaded" : "imageBlockedOrMissing"),
  });
  syncPreviewFromEditorScroll(currentEditor().scrollTop || 0);
  return typesetPreviewMath(container, {
    isCurrent: () => activeDocument()?.id === model.id && model.preview === payload,
    errorLabel: t("previewMathFailed"),
  });
}

/**
 * Redraw the authoring preview, one at a time.
 *
 * Same engine, same single job slot as the export preview: a second preview
 * sent while one is still composing is refused, and the refusal reached the
 * reader as "Preview could not be generated" over a healthy document. Typing
 * during a slow render is the ordinary way to hit that.
 */
const writePreviewFlight = createSingleFlight(() => drawWritePreview());

function refreshPreview() {
  return writePreviewFlight.run();
}

async function drawWritePreview() {
  const sequence = ++state.previewSequence;
  const model = activeDocument();
  if (!model || !isMarkdownModel(model) || !model.content.trim()) {
    if (model) model.preview = null;
    renderPreview(model);
    return;
  }
  const context = requestContext(model);
  $("#preview-loading").classList.remove("hidden");
  $("#reading-loading")?.classList.remove("hidden");
  try {
    const result = await previewDocumentText({ path: model.path, content: model.content, options: previewOptions() });
    if (sequence !== state.previewSequence || !contextIsCurrent(context)) return;
    model.preview = result;
    model.previewContentVersion = model.contentVersion;
    model.diagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
    // Local typesetting must not retain the engine's single-flight slot.
    // Opening another document while MathJax starts still needs a new payload.
    void renderPreview(model);
    renderCitations(model);
    renderProblems(model);
    renderContentStatus();
  } catch (error) {
    if (sequence !== state.previewSequence || !contextIsCurrent(context)) return;
    const payload = errorPayload(error);
    model.diagnostics = payload?.details?.diagnostics || payload?.diagnostics || [];
    renderProblems(model);
    renderPreviewMessage(t("previewFailed"), errorText(error));
  } finally {
    if (sequence === state.previewSequence) {
      $("#preview-loading").classList.add("hidden");
      $("#reading-loading")?.classList.add("hidden");
    }
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
    model.validationContentVersion = model.contentVersion;
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
    await allowDocumentImages(model);
    if (sequence !== state.assetSequence || !contextIsCurrent(context, { requireContent: false })) return;
    renderAssets(Array.isArray(result.assets) ? result.assets : []);
  } catch (error) {
    if (sequence !== state.assetSequence || !contextIsCurrent(context, { requireContent: false })) return;
    renderAssets([]);
    toast(errorText(error), "error");
  }
}

async function importAsset() {
  if (!documentEditable()) return;
  const model = activeDocument();
  if (!model?.path || !isMarkdownModel(model)) {
    toast(t("saveBeforeAsset"), "error");
    return;
  }
  const context = requestContext(model);
  try {
    const source = await invoke("pick_document_asset");
    if (!documentEditable()) return;
    if (!source) return;
    if (!contextIsCurrent(context, { requireContent: false })) return;
    const asset = await importDocumentAsset(model.path, source);
    if (!contextIsCurrent(context, { requireContent: false })) return;
    await allowDocumentImages(model);
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

function applySidebarContext() {
  const documentOnly = ["outline", "frontmatter", "assets", "citations"];
  const name = !isMarkdownModel(activeDocument()) && documentOnly.includes(state.activeSidebar)
    ? (state.project ? "project" : "problems") : state.activeSidebar;
  for (const button of $$("[data-sidebar]")) {
    const active = button.dataset.sidebar === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  }
  for (const panel of $$("[data-panel]")) {
    const active = panel.dataset.panel === name;
    panel.classList.toggle("active", active);
    panel.setAttribute("aria-hidden", String(!active));
    panel.inert = !active;
  }
  return name;
}

function activateSidebar(name) {
  if (name === "outline") { activateNavigator("outline"); return; }
  if ($(`[data-sidebar="${name}"]`)?.disabled) return;
  if (!state.workspaceLayout.sidebarOpen) {
    state.workspaceLayout.sidebarOpen = true;
    if (matchMedia("(max-width: 1100px)").matches) state.workspaceLayout.filesOpen = false;
    applyWorkspaceLayout({ persist: true });
  }
  state.activeSidebar = name;
  applySidebarContext();
  if (name === "assets") refreshAssets();
  if (name === "frontmatter") loadFrontMatterForm(activeDocument());
  if (name === "project") renderProjectWorkspace();
  if (name === "citations") refreshBibliography();
}

function goToLine(line, column = 1) {
  if (effectiveViewMode() === "read") {
    const target = $("#reading-document")?.querySelector(`[data-source-line="${Number(line) || 1}"]`);
    if (target) {
      target.scrollIntoView({ block: "start", behavior: "instant" });
      $("#reading-document")?.focus({ preventScroll: true });
      return;
    }
    setViewMode("source");
  }
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

function findSnapshot() {
  return { documentId: activeDocument()?.id, text: currentEditor().value, query: $("#find-query").value };
}

function updateFindMatches(options = {}) {
  const { matches, index } = findSession.refresh(findSnapshot(), options);
  $("#find-count").textContent = matches.length ? `${index + 1}/${matches.length}` : "0/0";
  return matches;
}

function selectFindMatch(index, { direction = null } = {}) {
  const snapshot = findSnapshot();
  const match = direction === null ? findSession.select(snapshot, index) : findSession.move(snapshot, direction);
  if (!match) return;
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
  updateFindMatches();
  updateEditorMetrics();
}

function openFind({ replace = false } = {}) {
  // Search selects the actual Markdown, and replacement requires an explicit
  // visible editing surface rather than changing a hidden reader buffer.
  if (effectiveViewMode() === "read") setViewMode("source");
  $("#find-bar").classList.remove("hidden");
  $("#replace-query").classList.toggle("hidden", !replace);
  $("#replace-one").classList.toggle("hidden", !replace);
  $("#replace-all").classList.toggle("hidden", !replace);
  const editor = currentEditor();
  const selected = editor.value.slice(editor.selectionStart, editor.selectionEnd);
  if (selected && !selected.includes("\n")) $("#find-query").value = selected;
  updateFindMatches({ reset: true });
  $("#find-query").focus();
  $("#find-query").select();
}

function closeFind() {
  $("#find-bar").classList.add("hidden");
  findSession.clear();
  currentEditor().focus();
}

function moveFind(direction) {
  selectFindMatch(null, { direction });
}

function replaceCurrentMatch() {
  if (!documentEditable()) return;
  const editor = currentEditor();
  const match = findSession.current(findSnapshot());
  if (!match) return;
  const replacement = $("#replace-query").value;
  applyEditorResult(replaceSelection(editor.value, match.start, match.end, replacement));
  updateFindMatches({ anchor: match.start + replacement.length });
  const { index } = findSession.refresh(findSnapshot());
  if (index >= 0) selectFindMatch(index);
}

function replaceAllMatches() {
  if (!documentEditable()) return;
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
  if (!documentEditable()) return;
  const editor = currentEditor();
  editor.value = result.text;
  editor.focus();
  editor.setSelectionRange(result.start, result.end);
  onEditorInput();
}

function applyEditorContent(content) {
  if (!documentEditable()) return;
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
  if (!documentEditable() || !isMarkdownModel(model)) return;
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
function togglePopoverMenu(menuSelector, buttonSelector, force) {
  const menu = $(menuSelector);
  const button = $(buttonSelector);
  if (!menu || !button) return;
  const open = force === undefined ? menu.classList.contains("hidden") : force;
  menu.classList.toggle("hidden", !open);
  button.setAttribute("aria-expanded", String(open));
  if (!open) return;
  const box = button.getBoundingClientRect();
  menu.style.top = `${box.bottom + 4}px`;
  // Anchored to the button's leading edge, and kept inside the window: the
  // strip mirrors, so the same menu opens from the other side in Persian.
  const start = document.documentElement.dir === "rtl"
    ? window.innerWidth - box.right
    : box.left;
  const room = window.innerWidth - menu.offsetWidth - 8;
  menu.style.insetInlineStart = `${Math.max(8, Math.min(start, room))}px`;
  menu.querySelector("button")?.focus();
}

function toggleHeadingMenu(force) {
  togglePopoverMenu("#heading-menu", "#heading-menu-button", force);
}

function toggleInsertMenu(force) {
  togglePopoverMenu("#insert-menu", "#insert-menu-button", force);
}

function toggleWritingAppearance(force) {
  togglePopoverMenu("#writing-appearance", "#writing-appearance-button", force);
  if (!$("#writing-appearance").classList.contains("hidden")) $("#writing-font")?.focus();
}

/* ---- The format bar keeps every control reachable -------------------------
 *
 * Nineteen controls in seven groups do not fit a narrow editor sheet. The bar
 * used to scroll them, with the scrollbar suppressed, so at 1280x900 in split
 * view five of them — quote, callout, table, code block, rule — were simply
 * not on screen and nothing said so. Groups that do not fit move into a menu
 * instead: the buttons are the same elements, so a command behaves the same
 * whether it is clicked on the bar, in the menu, from the palette or from its
 * shortcut.
 */

/** The bar, its trigger, its menu, and the groups allowed to move. */
function formatBarParts() {
  const bar = document.querySelector(".format-bar");
  const menu = $("#format-overflow-menu");
  const group = $("#format-overflow-group");
  if (!bar || !menu || !group) return null;
  return { bar, menu, group, trigger: $("#format-overflow-button") };
}

function toggleFormatOverflowMenu(force) {
  const parts = formatBarParts();
  if (!parts) return;
  togglePopoverMenu("#format-overflow-menu", "#format-overflow-button", force);
}

/**
 * Decide what fits and move the rest, after every change to the bar's width.
 *
 * The strip is measured rather than modelled. `.format-group-end` is sticky
 * and paints its own background, so a control it covers is still inside the
 * strip's box: not clipped, not visible, and not something a geometry check
 * can see. Asking the browser whether the strip overflows after each move
 * cannot disagree with the browser.
 */
function syncFormatBarOverflow() {
  const parts = formatBarParts();
  if (!parts) return;
  const movable = [...parts.bar.querySelectorAll("[data-format-movable]"),
                   ...parts.menu.querySelectorAll("[data-format-movable]")];
  const groups = movable.filter((node) => node.classList.contains("format-group"));
  if (!groups.length) return;

  // Focus would be lost with the button it is on, so it moves to the trigger
  // before any button can leave the bar.
  const focused = document.activeElement;
  if (focused instanceof HTMLElement && groups.some((node) => node.contains(focused))) {
    parts.trigger?.focus({ preventScroll: true });
  }

  const parked = fitToolbarGroups({
    count: groups.length,
    restore: () => {
      for (const node of movable) parts.bar.insertBefore(node, parts.group);
      parts.group.classList.add("hidden");
    },
    overflows: () => parts.bar.scrollWidth > parts.bar.clientWidth + 1,
    onOverflow: () => parts.group.classList.remove("hidden"),
    // Parked from the end backwards and prepended, so the menu reads in the
    // same order the strip did.
    park: (index) => {
      const node = groups[index];
      const previous = node.previousElementSibling;
      const divider = previous?.classList.contains("formatting-divider") ? previous : null;
      parts.menu.prepend(node);
      if (divider) parts.menu.insertBefore(divider, node);
    },
  });
  if (!parked.length) toggleFormatOverflowMenu(false);
}

/**
 * Move focus to the control before or after the editor.
 *
 * Tab indents inside the document, so Escape arms the next Tab to leave
 * instead. Where it lands is the workbench's business rather than the
 * editor's: deciding it here means the workbench's own focus order, in both
 * directions, on every webview — the browsers' contenteditable release only
 * goes forwards and only when nothing else claimed the Escape first.
 */
function moveFocusOutOfEditor(backwards = false) {
  const surface = $(".editor-surface");
  if (!surface) return;
  const candidates = focusableElements(document.body)
    .filter((element) => !surface.contains(element) && element.offsetParent !== null);
  if (!candidates.length) return;
  const before = [];
  const after = [];
  for (const element of candidates) {
    const where = surface.compareDocumentPosition(element);
    if (where & Node.DOCUMENT_POSITION_PRECEDING) before.push(element);
    else if (where & Node.DOCUMENT_POSITION_FOLLOWING) after.push(element);
  }
  // Wrapping matches what the browser does at either end of the document.
  const target = backwards
    ? (before.at(-1) || after.at(-1))
    : (after[0] || before[0]);
  target?.focus();
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
  if (!model || !isMarkdownModel(model) || !model.content.trim()) {
    toast(t("previewEmpty"));
    return;
  }
  const context = requestContext(model);
  try {
    const result = model.preview && model.previewContentVersion === model.contentVersion
      ? model.preview
      : await previewDocumentText({ path: model.path, content: model.content, options: previewOptions() });
    if (!contextIsCurrent(context)) {
      toast(t("copyDocumentChanged"));
      return;
    }
    const article = document.createElement("div");
    article.append(safePreviewHtml(`${result.body_html || ""}${result.reference_lists_html || ""}${result.bibliography_html || ""}`, "clipboard-"));
    await typesetPreviewMath(article, { isCurrent: () => contextIsCurrent(context), errorLabel: t("previewMathFailed") });
    if (!contextIsCurrent(context)) return;
    if (await copyToClipboard(article.textContent || "", { html: article.innerHTML })) toast(t("copied"), "success");
  } catch (error) {
    toast(errorText(error), "error");
  }
}

async function pasteAsPlainText() {
  const model = activeDocument();
  if (!documentEditable()) return;
  const context = requestContext(model);
  const intent = state.documentActivationSequence;
  const editor = currentEditor();
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  try {
    const text = await navigator.clipboard.readText();
    if (!contextIsCurrent(context) || intent !== state.documentActivationSequence
      || !documentEditable() || editor.selectionStart !== start || editor.selectionEnd !== end) return;
    if (text) applyEditorResult(replaceSelection(editor.value, start, end, text));
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
  const editable = documentEditable() && isMarkdownModel(model);
  const hasSelection = currentEditor().selectionStart !== currentEditor().selectionEnd;

  const items = [
    { key: "copy", label: t("copy"), enabled: hasSelection, run: () => copyToClipboard(selectionOrDocument()) },
    { key: "copyHtml", label: t("copyAsHtml"), enabled: isMarkdownModel(model) && Boolean(model?.content.trim()), run: copyAsHtml },
    { key: "copyPlain", label: t("copyAsPlainText"), enabled: true, run: () => copyToClipboard(selectionOrDocument()) },
    { key: "paste", label: t("pasteAsPlainText"), enabled: editable, run: pasteAsPlainText },
    { separator: true },
    { key: "image", label: t("insertImage"), enabled: editable, run: importAsset },
    { key: "citation", label: t("insertCitation"), enabled: editable, run: () => editorCommand("citation") },
    { key: "table", label: t("insertTable"), enabled: editable, run: () => editorCommand("table") },
    { separator: true },
    { key: "validate", label: t("checkDocument"), enabled: isMarkdownModel(model), run: validateActiveDocument },
    { key: "export", label: t("exportPdf"), enabled: isMarkdownModel(model), run: exportActiveDocument },
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
    button.dataset.contextAction = item.key;
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
  if (!documentEditable() || !isMarkdownModel(model)) return;
  const form = event.currentTarget;
  let content = model.content;
  for (const key of ["title", "subtitle", "author", "lang", "dir"]) {
    const input = form.elements.namedItem(key);
    if (!input.disabled && input.value !== frontMatterFormBaseline.get(key)) {
      content = upsertFrontMatter(content, key, input.value);
    }
  }
  const toc = form.elements.namedItem("toc");
  if (!toc.disabled && toc.checked !== frontMatterFormBaseline.get("toc")) {
    content = upsertFrontMatter(content, "toc", toc.checked);
  }
  if (content === model.content) return;
  applyEditorContent(content);
  loadFrontMatterForm(model);
  schedulePreview(80);
}

async function exportActiveDocument() {
  const model = activeDocument();
  if (!model || !isMarkdownModel(model)) return;
  const intent = state.documentActivationSequence;
  if (!model.path || documentDirty(model)) {
    const saved = await saveActiveDocument();
    if (!saved) return;
  }
  if (intent !== state.documentActivationSequence || activeDocument()?.id !== model.id) return;
  if (documentDirty(model)) {
    toast(t("exportNeedsCurrentSave"));
    return;
  }
  openExportSource(model.path);
}

// ---------------------------------------------------------------------------
// Runtime lifecycle and event wiring
// ---------------------------------------------------------------------------
/**
 * Ask the engine what it can do, once.
 *
 * The interface and the engine ship together, but they do not always run
 * together: a desktop build carries a compiled sidecar, and a rebuilt front end
 * on an unrebuilt runtime is a normal state during development and after a
 * partial update. Knowing which methods exist lets a feature stand down
 * gracefully instead of putting a protocol error on screen.
 */
async function engineCapabilities() {
  try {
    const capabilities = await invoke("sidecar_request", {
      request_id: requestId("capabilities"),
      method: "system.capabilities",
      params: {},
    });
    state.engineMethods = new Set(
      Array.isArray(capabilities?.methods) ? capabilities.methods.map(String) : [],
    );
  } catch {
    // An engine that cannot describe itself is assumed to support everything;
    // the individual call will fail on its own terms if it does not.
    state.engineMethods = null;
  }
}

function engineSupports(method) {
  return !state.engineMethods || state.engineMethods.has(method);
}

async function engineHealth() {
  const element = $("#engine-state");
  try {
    const health = await invoke("sidecar_request", { request_id: requestId("health"), method: "system.health", params: {} });
    element.dataset.state = "ready";
    element.querySelector("span").dataset.i18n = "engineReady";
    element.querySelector("span").textContent = t("engineReady");
    $("#runtime-detail").textContent = `${health.engine_version || ""} · ${health.runtime?.platform || t("localRuntime")}`;
    await engineCapabilities();
  } catch (error) {
    element.dataset.state = "error";
    element.querySelector("span").dataset.i18n = "engineUnavailable";
    element.querySelector("span").textContent = t("engineUnavailable");
    $("#runtime-detail").textContent = t("sidecarUnavailableDetail");
    toast(errorText(error), "error");
  }
}

function bindEvents() {
  // Fixed popovers belong to the viewport. Keeping them inside a size-query
  // container would change their containing block and clip them over a pane.
  for (const menu of $$(".popover-menu, #editor-context-menu")) document.body.append(menu);
  $("#workspace-toggle-preview").addEventListener("click", toggleSidePreview);
  $("#document-mode-help").addEventListener("click", () => modalManager.open($("#view-guide-modal")));
  $("#close-view-guide").addEventListener("click", () => modalManager.close($("#view-guide-modal")));
  $("#workflow-new").addEventListener("click", createUntitledDocument);
  $("#home-button").addEventListener("click", () => showView("start"));
  $("#command-button").addEventListener("click", openCommandPalette);
  $("#help-button").addEventListener("click", openHelp);
  $("#settings-button").addEventListener("click", openSettings);
  $("#template-help").addEventListener("click", openHelp);
  for (const button of $$("button[data-view-mode]")) {
    button.addEventListener("click", () => setViewMode(button.dataset.viewMode));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const buttons = $$("button[data-view-mode]").filter((item) => !item.disabled);
      if (buttons.length < 2) return;
      const index = buttons.indexOf(button);
      const rtl = document.documentElement.dir === "rtl";
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
        : (index + ((event.key === "ArrowRight") !== rtl ? 1 : -1) + buttons.length) % buttons.length;
      setViewMode(buttons[next].dataset.viewMode);
      buttons[next].focus();
    });
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
    $(`#option-tab-${items[next].dataset.group}`)?.focus({ preventScroll: true });
  });
  $("#preview-zoom-in").addEventListener("click", () => exportPreviewDeck()?.zoomBy(1));
  $("#preview-zoom-out").addEventListener("click", () => exportPreviewDeck()?.zoomBy(-1));
  $("#preview-fit-width").addEventListener("click", () => exportPreviewDeck()?.setZoomMode("fit-width"));
  $("#preview-fit-page").addEventListener("click", () => exportPreviewDeck()?.setZoomMode("fit-page"));
  $("#preview-guides").addEventListener("click", () => exportPreviewDeck()?.toggleGuides());
  $("#preview-prev-page").addEventListener("click", () => movePreviewPage(-1));
  $("#preview-next-page").addEventListener("click", () => movePreviewPage(1));
  $("#workflow-quick").addEventListener("click", () => {
    state.exportReturnView = "start";
    showView("export");
    schedulePdfPreview(0);
  });
  $("#workflow-open").addEventListener("click", chooseAuthoringFiles);
  $("#workflow-project").addEventListener("click", chooseProjectDirectory);
  $("#workflow-book").addEventListener("click", openNewBookModal);
  $("#export-back").addEventListener("click", () => {
    showView(state.exportReturnView);
    if (state.exportReturnView === "workspace") focusDocument();
  });
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
  $("#workspace-toggle-files")?.addEventListener("click", () => toggleWorkspacePane("files"));
  $("#workspace-toggle-formatting")?.addEventListener("click", () => toggleWorkspacePane("formatting"));
  $("#writing-appearance-button")?.addEventListener("click", () => toggleWritingAppearance());
  $("#writing-appearance-close")?.addEventListener("click", () => {
    toggleWritingAppearance(false); $("#writing-appearance-button").focus();
  });
  $("#writing-font")?.addEventListener("change", (event) => updateDocumentView({ writingFont: event.target.value }));
  $("#writing-density")?.addEventListener("change", (event) => updateDocumentView({ writingDensity: event.target.value }));
  $("#writing-zoom")?.addEventListener("input", (event) => updateDocumentView({ documentZoom: Number(event.target.value) }));
  $("#writing-appearance-reset")?.addEventListener("click", () => updateDocumentView({ documentZoom: 100, writingDensity: "comfortable", writingFont: "document" }));
  $("#writing-appearance")?.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault(); event.stopPropagation();
    toggleWritingAppearance(false); $("#writing-appearance-button").focus();
  });
  const navigatorTabs = $$("[data-navigator-tab]");
  for (const button of navigatorTabs) {
    button.addEventListener("click", () => activateNavigator(button.dataset.navigatorTab));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const tabs = navigatorTabs.filter((tab) => !tab.disabled);
      const backwards = event.key === (document.documentElement.dir === "rtl" ? "ArrowRight" : "ArrowLeft");
      const index = tabs.indexOf(button);
      const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs.at(-1) : tabs[(index + (backwards ? -1 : 1) + tabs.length) % tabs.length];
      if (next) { activateNavigator(next.dataset.navigatorTab); next.focus(); }
    });
  }
  $("#outline-filter")?.addEventListener("input", (event) => {
    outlineNavigator?.setFilter(event.target.value);
    $("#outline-collapse-all").disabled = Boolean(event.target.value);
  });
  $("#outline-expand-all")?.addEventListener("click", () => outlineNavigator?.expandAll());
  $("#outline-collapse-all")?.addEventListener("click", () => outlineNavigator?.collapseAll());
  $("#outline-follow")?.addEventListener("change", (event) => outlineNavigator?.setFollow(event.target.checked));
  let lastTextWheel = 0;
  document.addEventListener("wheel", (event) => {
    if (!(event.ctrlKey || event.metaKey) || !event.deltaY || !event.target.closest(".editor-surface,.reading-document,.preview-document,#book-review-document")) return;
    event.preventDefault();
    const now = Date.now();
    if (now - lastTextWheel < 80) return;
    lastTextWheel = now;
    changeDocumentZoom(event.deltaY < 0 ? 1 : -1);
  }, { passive: false });
  $("#document-zoom-out")?.addEventListener("click", () => changeDocumentZoom(-1));
  $("#document-zoom-in")?.addEventListener("click", () => changeDocumentZoom(1));
  $("#document-zoom-reset")?.addEventListener("click", () => changeDocumentZoom(0));
  $("#document-toggle-width")?.addEventListener("click", () => updateDocumentView({ writingWidth: state.preferences.writingWidth === "full" ? "readable" : "full" }));
  $("#workspace-quick-open")?.addEventListener("click", () => navigationPicker.open("files"));
  $("#navigator-new")?.addEventListener("click", createUntitledDocument);
  $("#tab-new-document")?.addEventListener("click", createUntitledDocument);
  $("#navigator-open")?.addEventListener("click", chooseAuthoringFiles);
  $("#navigator-open-project")?.addEventListener("click", chooseProjectDirectory);
  $("#navigator-close")?.addEventListener("click", () => toggleWorkspacePane("files"));
  $("#inspector-close")?.addEventListener("click", () => toggleWorkspacePane("sidebar"));
  $("#workspace-focus")?.addEventListener("click", () => { updatePreference({ focusMode: !state.preferences.focusMode }); focusDocument(); });
  $("#exit-focus-mode")?.addEventListener("click", () => { updatePreference({ focusMode: false }); focusDocument(); });
  $("#workspace-commands")?.addEventListener("click", openCommandPalette);
  $("#workspace-settings")?.addEventListener("click", openSettings);
  $("#workspace-help")?.addEventListener("click", openHelp);
  $("#file-resizer")?.addEventListener("pointerdown", (event) => beginPaneResize(event, "files"));
  $("#file-resizer")?.addEventListener("keydown", (event) => resizePaneWithKeyboard(event, "files"));
  $("#reading-document")?.addEventListener("scroll", (event) => {
    if (readingDocumentId && state.preferences.viewMode === "read" && event.currentTarget.getClientRects().length) {
      readingScroll.set(readingDocumentId, event.currentTarget.scrollTop);
      outlineNavigator?.setActiveLine(readingSourceLine(), { scroll: true });
    }
  });
  $("#document-actions-menu")?.addEventListener("click", (event) => {
    if (event.target.closest("button")) event.currentTarget.open = false;
  });
  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest("#document-actions-menu")) $("#document-actions-menu")?.removeAttribute("open");
  });
  let compactWorkspace = matchMedia("(max-width: 1100px)").matches;
  window.addEventListener("resize", () => {
    const next = matchMedia("(max-width: 1100px)").matches;
    if (next && !compactWorkspace) {
      state.workspaceLayout.filesOpen = false;
      state.workspaceLayout.sidebarOpen = false;
      applyWorkspaceLayout();
    }
    compactWorkspace = next;
  });
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
  // Passing the handler directly gave the click event to the function's first
  // parameter, which it compared against a sequence number and always found
  // unequal — the button returned without ever rendering anything.
  $("#refresh-preview").addEventListener("click", () => void refreshPreview());
  $("#refresh-reading").addEventListener("click", () => void refreshPreview());
  for (const checkbox of $$('[data-content-auto]')) checkbox.addEventListener("change", () => {
    updatePreference({ autoPreview: checkbox.checked });
    if (checkbox.checked && contentViewVisible()) void refreshPreview();
    else schedulePreview();
  });
  $("#frontmatter-form").addEventListener("submit", applyFrontMatter);
  $("#find-query").addEventListener("input", () => { if (updateFindMatches({ reset: true }).length) selectFindMatch(0); });
  $("#find-query").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); moveFind(event.shiftKey ? -1 : 1); } if (event.key === "Escape") closeFind(); });
  $("#find-previous").addEventListener("click", () => moveFind(-1));
  $("#find-next").addEventListener("click", () => moveFind(1));
  $("#replace-one").addEventListener("click", replaceCurrentMatch);
  $("#replace-all").addEventListener("click", replaceAllMatches);
  $("#close-find").addEventListener("click", closeFind);
  $$('[data-editor-command]').forEach((button) => button.addEventListener("click", () => {
    if (button.closest("#heading-menu")) toggleHeadingMenu(false);
    if (button.closest("#insert-menu")) toggleInsertMenu(false);
    editorCommand(button.dataset.editorCommand);
  }));
  $("#heading-menu-button").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleHeadingMenu();
  });
  $("#insert-menu-button").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleInsertMenu();
  });
  $("#insert-image").addEventListener("click", () => {
    toggleInsertMenu(false);
    void importAsset();
  });
  $("#insert-menu").addEventListener("keydown", (event) => {
    const items = [...$("#insert-menu").querySelectorAll("button")];
    const index = items.indexOf(document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      toggleInsertMenu(false);
      $("#insert-menu-button").focus();
      return;
    }
    if (!["ArrowUp", "ArrowDown"].includes(event.key) || index < 0) return;
    event.preventDefault();
    const next = event.key === "ArrowDown"
      ? (index + 1) % items.length
      : (index - 1 + items.length) % items.length;
    items[next].focus();
  });
  $("#format-overflow-button").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleFormatOverflowMenu();
  });
  $("#format-overflow-menu").addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    toggleFormatOverflowMenu(false);
    $("#format-overflow-button").focus();
  });
  $("#editor-context-menu").addEventListener("keydown", (event) => {
    if (event.key === "Escape" || event.key === "Tab") {
      event.preventDefault();
      closeEditorContextMenu();
      focusDocument();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = [...event.currentTarget.querySelectorAll("button:not([disabled])")];
    const index = items.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
      : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  });
  // A command run from the menu has done what the user opened it for.
  $("#format-overflow-menu").addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest("button")) {
      toggleFormatOverflowMenu(false);
    }
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
    if (!target?.closest("#insert-menu, #insert-menu-button")) toggleInsertMenu(false);
    if (!target?.closest("#writing-appearance, #writing-appearance-button")) toggleWritingAppearance(false);
    if (!target?.closest("#format-overflow-menu, #format-overflow-button")) {
      toggleFormatOverflowMenu(false);
    }
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
      const rtl = document.documentElement.dir === "rtl";
      if (event.key === "ArrowUp" || event.key === (rtl ? "ArrowRight" : "ArrowLeft")) targetIndex = (index - 1 + sidebarButtons.length) % sidebarButtons.length;
      if (event.key === "ArrowDown" || event.key === (rtl ? "ArrowLeft" : "ArrowRight")) targetIndex = (index + 1) % sidebarButtons.length;
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
      // The dialog manager and editor menus get the first Escape. Closing a
      // picker must not also leave the writer's focus mode underneath it.
      if (event.defaultPrevented) return;
      const documentMenuOpen = Boolean($("#document-actions-menu")?.open);
      closeEditorContextMenu();
      $("#document-actions-menu")?.removeAttribute("open");
      toggleHeadingMenu(false);
      toggleInsertMenu(false);
      if (documentMenuOpen) {
        $("#document-actions-menu summary")?.focus();
        return;
      }
      // A mode that hides the way out has to have one.
      if (state.preferences.focusMode && !modalManager.hasOpenModal()) {
        updatePreference({ focusMode: false });
        focusDocument();
      } else if (!modalManager.hasOpenModal() && matchMedia("(max-width: 1100px)").matches
        && (state.workspaceLayout.filesOpen || state.workspaceLayout.sidebarOpen)) {
        state.workspaceLayout.filesOpen = false;
        state.workspaceLayout.sidebarOpen = false;
        applyWorkspaceLayout();
        focusDocument();
      }
    }
    if (event.key === "F1") {
      event.preventDefault();
      if (!modalManager.hasOpenModal()) openHelp();
      return;
    }
    const key = authoringShortcutKey(event);
    if (!key) return;
    if (modalManager.hasOpenModal()) return;
    const formControl = event.target instanceof Element
      && event.target.matches("input,textarea,select,[contenteditable='true']")
      && !event.target.closest(".editor-surface");
    if (formControl) return;
    if ($("#workspace-view").classList.contains("active") && !event.altKey && ["+", "=", "-", "0"].includes(key)) {
      event.preventDefault();
      changeDocumentZoom(key === "0" ? 0 : key === "-" ? -1 : 1);
    } else if (key === "p" && event.shiftKey) {
      event.preventDefault();
      openCommandPalette();
    } else if (key === "p") {
      event.preventDefault();
      navigationPicker.open("files");
    } else if (key === "o" && event.shiftKey) {
      event.preventDefault();
      navigationPicker.open("headings");
    } else if (key === "\\") {
      event.preventDefault();
      toggleWorkspacePane("files");
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

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || modalManager.hasOpenModal()) return;
    const compactDrawer = event.target.closest?.(".editor-surface")
      && matchMedia("(max-width: 1100px)").matches
      && (state.workspaceLayout.filesOpen || state.workspaceLayout.sidebarOpen);
    if (!state.preferences.focusMode && !compactDrawer) return;
    const completion = $(".cm-tooltip-autocomplete");
    const editorPopupFocused = event.target.closest?.(".cm-selection-toolbar");
    if (completion?.getClientRects().length || editorPopupFocused) return;
    if (["#editor-context-menu", "#insert-menu", "#heading-menu", "#format-overflow-menu"]
      .some((selector) => !$(selector)?.classList.contains("hidden"))) return;
    event.preventDefault();
    event.stopPropagation();
    if (state.preferences.focusMode) updatePreference({ focusMode: false });
    else {
      state.workspaceLayout.filesOpen = false;
      state.workspaceLayout.sidebarOpen = false;
      applyWorkspaceLayout();
    }
    focusDocument();
  }, true);

  window.addEventListener("beforeunload", () => {
    for (const model of state.documents) if (documentDirty(model)) saveRecovery(model);
  });

  // Every way the format bar can change width — the window, a pane toggle, a
  // resize drag, the view mode, focus mode — arrives here as one signal.
  const formatBar = document.querySelector(".format-bar");
  if (formatBar && typeof ResizeObserver === "function") {
    let pending = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(syncFormatBarOverflow);
    }).observe(formatBar);
  } else {
    window.addEventListener("resize", syncFormatBarOverflow);
  }
  let toastPlacementFrame = 0;
  const scheduleToastPlacement = () => {
    cancelAnimationFrame(toastPlacementFrame);
    toastPlacementFrame = requestAnimationFrame(syncExportToastPlacement);
  };
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(scheduleToastPlacement);
    for (const selector of ["#export-view", "#export-view .export-dock"]) {
      const region = $(selector);
      if (region) observer.observe(region);
    }
  }
  window.addEventListener("resize", scheduleToastPlacement);
  window.visualViewport?.addEventListener("resize", scheduleToastPlacement);
}

async function boot() {
  modalManager = createModalManager(document);
  navigationPicker = createNavigationPicker({ manager: modalManager, t,
    getEntries: (scope) => scope === "headings"
      ? extractOutline(activeDocument()?.content || "").map((item) => ({ id: `heading:${item.line}`, label: item.title, detail: `${t("lineShort")} ${item.line}`, line: item.line, level: item.level, documentId: activeDocument()?.id, contentVersion: activeDocument()?.contentVersion }))
      : documentNavigationEntries(state.documents, state.project),
    onChoose: async (entry, scope) => {
      if (scope === "headings") {
        if (entry.documentId === activeDocument()?.id && entry.contentVersion === activeDocument()?.contentVersion) goToLine(entry.line);
        else focusDocument();
      }
      else {
        showView("workspace");
        if (entry.documentId) await activateDocument(entry.documentId);
        else await openProjectRelativeFile(entry.relativePath);
      }
    },
  });
  // An initially open drawer must not obscure the writing surface on a small
  // window. Explicit toggles still open one drawer at a time.
  if (matchMedia("(max-width: 1100px)").matches) {
    state.workspaceLayout.filesOpen = false;
    state.workspaceLayout.sidebarOpen = false;
  }
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
    locale: state.locale,
    strings: editorStrings(),
    theme: document.documentElement.dataset.theme,
    mode: editorModeForView(state.preferences.viewMode),
    typewriter: state.preferences.typewriter,
    onContextMenu: openEditorContextMenu,
    onLeaveEditor: moveFocusOutOfEditor,
    resolveAsset: resolveEditorAsset,
    renderMath: (container, { isCurrent } = {}) => typesetPreviewMath(container, { isCurrent, errorLabel: t("previewMathFailed") }),
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
        const restoration = openAuthoringPaths(session.paths);
        const activationSequence = state.documentActivationSequence;
        await restoration;
        const active = findDocumentByPath(state.documents, session.activePath);
        if (active && activationSequence === state.documentActivationSequence) await activateDocument(active.id);
      }
    }
  } catch (error) {
    toast(errorText(error), "error");
  }
  const draftActivationSequence = state.documentActivationSequence;
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
  if (restoredDrafts && draftActivationSequence === state.documentActivationSequence) {
    showView("workspace");
    renderWorkspace();
    schedulePreview(120);
  }
  if (!state.documents.length && !state.preferences.onboardingComplete) {
    openOnboarding();
  }
}

boot();
