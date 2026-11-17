import { createDocumentPersistence } from "./features/documents/persistence.mjs";
import { createDocumentTabs } from "./features/documents/tabs.mjs";
import { createBookChapters } from "./features/books/chapters.mjs";
import { createBookOperations } from "./features/books/operations.mjs";
import { createBookCreation } from "./features/books/creation.mjs";
import { createExportController } from "./features/export/controller.mjs";
import { createPreviewSanitizer } from "./preview/sanitize.mjs";
import { createNotifications } from "./ui/notifications.mjs";
import { createUpdater } from "./features/settings/updater.mjs";
import { createSettingsController } from "./features/settings/controller.mjs";
import { createCommandPalette } from "./ui/command-palette.mjs";
import { createWorkspacePanes } from "./features/workspace/panes.mjs";
import { createProjectWorkspace } from "./features/workspace/project.mjs";
import {
  basename,
  defaultOutputPath,
  validateExportSelection,
} from "./features/export/export-request.mjs";
import { createTranslator, readLocalePreference, writeLocalePreference } from "./core/i18n.mjs";
import {
  onboardingIntentPresentation,
  onboardingPrimaryActionKey,
  normalizeOnboardingIntent,
} from "./core/onboarding.mjs";
import { PRESETS, presetById } from "./features/export/presets.mjs";
import { createExportOptionsPanel } from "./features/export/export-options-panel.mjs";
import { spriteIcon } from "./ui/icons.mjs";
import { addRecent, readRecents, writeRecents } from "./features/documents/recents.mjs";
import { invoke, listen } from "./adapters/tauri.mjs";
import {
  createDocument,
  documentDirty,
  findDocumentByPath,
  markDocumentSaved,
  pathKey,
  updateDocumentContent,
} from "./core/documents.mjs";
import {
  readRecoveries,
  recoveryForPath,
  removeRecovery,
  saveRecovery,
} from "./features/documents/recovery.mjs";
import { readSession, writeSession } from "./features/documents/session.mjs";
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
import {
  documentImageAlts,
  documentImageSources,
  localImageDestination,
} from "./core/document-assets.mjs";
import { createEditorAdapter } from "./features/documents/editor-adapter.mjs";
import { mountDocumentContent } from "./preview/document-content.mjs";
import { safeOnlineImageURL } from "./preview/online-images.mjs";
import { interpolatePosition } from "./core/content-position.mjs";
import {
  captureDocumentContext,
  captureProjectContext,
  documentContextCurrent,
  projectContextCurrent,
} from "./core/request-context.mjs";
import { createSaveCoordinator } from "./core/save-coordinator.mjs";
import { createOutlineNavigator } from "./ui/outline-navigator.mjs";
import { createDocumentMetrics } from "./core/document-metrics.mjs";
import { authoringShortcutKey } from "./core/keyboard-shortcuts.mjs";
import { createWorkspaceToolbar } from "./features/workspace/workspace-toolbar.mjs";
import { compactDocumentLocation } from "./core/path-display.mjs";
import { createConfirmationQueue } from "./core/confirmation-queue.mjs";
import { createSingleFlight } from "./core/single-flight.mjs";
import { diagnosticLines, inlineDiagnosticsForDocument } from "./core/diagnostics.mjs";
import {
  DOCUMENT_ZOOM_MIN,
  DOCUMENT_ZOOM_MAX,
  applyPreferences,
  editorModeForView,
  nextDocumentZoom,
  previewVisibleForView,
  readPreferences,
  writePreferences,
} from "./features/settings/preferences.mjs";
import { templateContent, templateList } from "./core/templates.mjs";
import { readWorkspaceLayout } from "./features/workspace/workspace-layout.mjs";
import { documentNavigationEntries } from "./core/document-navigation.mjs";
import { createNavigationPicker } from "./ui/navigation-picker.mjs";
import { fitToolbarGroups } from "./core/toolbar-overflow.mjs";
import { createModalManager, focusableElements } from "./ui/modal-manager.mjs";
import { createPageDeck } from "./preview/page-deck.mjs";
import { typesetPreviewMath } from "./preview/math.mjs";
import { bibliographyIndex, readProjectFile } from "./adapters/project-api.mjs";
import {
  resetProjectSession,
  applyProjectSession,
  attachProjectMembership,
} from "./core/project-lifecycle.mjs";
import {
  importDocumentAsset,
  listDocumentAssets,
  previewDocumentPage,
  previewDocumentText,
  readDocument,
  readTextDocument,
  resolveMarkdownLink,
  validateDocumentText,
} from "./adapters/authoring-api.mjs";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const compactSidePanes = matchMedia("(max-width: 1100px)");
const state = {
  locale: readLocalePreference(undefined, navigator.language),
  presetId: "general",
  sourcePath: "",
  outputPath: "",
  activeRequestId: null,
  cancelledExportRequestId: null,
  outputResult: null,
  bookOutputPath: null,
  recents: readRecents(),
  documents: [],
  activeDocumentId: null,
  startTabs: [],
  activeStartTabId: null,
  tabOrder: [],
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
  compactDrawer: null,
  onboardingStep: 0,
  onboardingIntent: null,
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
const onlineImageOrigins = new WeakMap();
let imageScopeTimer = null;
const saveCoordinator = createSaveCoordinator({ isDirty: documentDirty });
const findSession = createFindSession();
const askConfirmation = createConfirmationQueue(presentConfirmation);
const translator = createTranslator(state.locale);
const t = (key) => translator.t(key);

const { toast } = createNotifications({ query: $ });
const { updateUi, initializeUpdater, checkUpdates, installAvailableUpdate } = createUpdater({
  state,
  query: $,
  t,
  toast,
  errorText,
  isDirty: documentDirty,
  confirm: askConfirmation,
  save: (model) => saveCoordinator.save(model, () => persistDocumentModel(model)),
  refreshAuthoring: () => updateAuthoringMode(activeDocument()),
});
const { openSettings, closeSettings, submitSettings, resetSettings } = createSettingsController({
  state,
  query: $,
  getModalManager: () => modalManager,
  applyInterfacePreferences,
  setLocale,
  t,
  toast,
});
const { renderCommandPalette, openCommandPalette, commandKeydown, resetCommandSelection } =
  createCommandPalette({
    query: $,
    queryAll: $$,
    getModalManager: () => modalManager,
    commandDefinitions,
    t,
    toast,
    errorText,
  });
const {
  applyWorkspaceLayout,
  applyNavigatorContext,
  activateNavigator,
  isCompactDrawer,
  workspacePaneOpen,
  setWorkspacePaneOpen,
  toggleWorkspacePane,
  resetWorkspacePaneSizes,
  closeCompactDrawer,
  beginPaneResize,
  resizePaneWithKeyboard,
} = createWorkspacePanes({
  state,
  query: $,
  queryAll: $$,
  compactSidePanes,
  activeDocument,
  isMarkdownModel,
  focusDocument,
});

const {
  chooseProjectDirectory,
  loadProject,
  refreshActiveProject,
  renderProjectWorkspace,
  cancelActiveProjectSearch,
  runProjectSearch,
} = createProjectWorkspace({
  state,
  query: $,
  activeDocument,
  openProjectRelativeFile,
  invalidateBookTaskForProjectChange: () => invalidateBookTaskForProjectChange(),
  applyProjectPayload,
  renderFileNavigator: () => renderFileNavigator(),
  showView,
  activateSidebar,
  closeCompactDrawer,
  setTruncatableText,
  t,
  toast,
  errorText,
  errorPayload,
});

const { saveActiveDocument, persistDocumentModel, requestCloseDocument, scheduleRecovery } =
  createDocumentPersistence({
    state,
    query: $,
    getEditor: () => editorAdapter,
    activeDocument,
    isMarkdownModel,
    saveCoordinator,
    activateDocument,
    activateStartTab,
    focusDocument,
    saveRecent,
    persistSession,
    renderWorkspace,
    renderDocumentTabs: () => renderDocumentTabs(),
    refreshActiveProject,
    setSaveState,
    askConfirmation,
    t,
    toast,
    errorText,
    errorPayload,
  });
const { renderDocumentTabs, revealActiveTab, renderFileNavigator } = createDocumentTabs({
  state,
  query: $,
  activeDocument,
  activateDocument,
  activateStartTab,
  closeStartTab,
  requestCloseDocument,
  closeCompactDrawer,
  setTruncatableText,
  t,
});
const { openChapterModal, closeChapterModal, bookProject, submitChapterModal, bookChapterRow } =
  createBookChapters({
    state,
    query: $,
    getModalManager: () => modalManager,
    activeDocument,
    currentProjectContext,
    projectContextIsCurrent,
    applyProjectPayload,
    openProjectRelativeFile,
    askConfirmation,
    setTruncatableText,
    t,
    toast,
    errorText,
  });
const {
  setBookOperationStatus,
  syncBookOperationControls,
  cancelActiveBookOperation,
  invalidateBookTaskForProjectChange,
  renderBookOutputResult,
  openBookOutput,
  validateActiveBook,
  previewActiveBook,
  exportActiveBook,
} = createBookOperations({
  state,
  query: $,
  queryAll: $$,
  getModalManager: () => modalManager,
  bookProject,
  currentProjectContext,
  projectContextIsCurrent,
  applyProjectPayload,
  askConfirmation,
  saveDocument: (model) =>
    saveCoordinator.save(model, () => persistDocumentModel(model, { refreshProjectOnSave: false })),
  refreshAuthoring: () => updateAuthoringMode(activeDocument()),
  renderProblems: () => renderProblems(activeDocument()),
  activateSidebar,
  safePreviewHtml: (...args) => safePreviewHtml(...args),
  requestId,
  setTruncatableText,
  t,
  toast,
  errorText,
  errorPayload,
});
const {
  folderNameFromTitle,
  openNewBookModal,
  closeNewBookModal,
  chooseBookParent,
  submitNewBookProject,
} = createBookCreation({
  state,
  query: $,
  getModalManager: () => modalManager,
  invalidateBookTaskForProjectChange,
  applyProjectPayload,
  showView,
  activateSidebar,
  openProjectRelativeFile,
  t,
  toast,
  errorText,
});
const {
  setExportStatus,
  renderExportStatus,
  invalidateExportStatus,
  setExportProgress,
  syncExportControls,
  validateExportDocument,
  exportDocument,
  cancelExport,
  openResult,
  updateExportMessage,
} = createExportController({
  state,
  query: $,
  t,
  toast,
  errorText,
  errorPayload,
  requestId,
  exportSelectionValid,
  exportOverrides,
  hideExportResult,
  showExportResult,
  saveRecent,
  releaseEngineForJob,
  refreshPreviewIfDirty: () => {
    if (exportPreviewDirty) schedulePdfPreview(0);
  },
});
const { safePreviewHtml } = createPreviewSanitizer({ t });

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
  return Boolean(
    model &&
    !model.readOnly &&
    !state.updateInstalling &&
    !state.bookPreparing &&
    effectiveViewMode() !== "read",
  );
}

function effectiveViewMode() {
  return activeDocument() && !isMarkdownModel(activeDocument())
    ? "source"
    : state.preferences.viewMode;
}

function contentViewVisible() {
  return (
    effectiveViewMode() === "read" ||
    (isMarkdownModel(activeDocument()) &&
      previewVisibleForView(effectiveViewMode(), state.preferences.sidePreview))
  );
}

function focusDocument() {
  if (!activeDocument()) $("#workflow-new")?.focus({ preventScroll: true });
  else if (effectiveViewMode() === "read") $("#reading-document")?.focus({ preventScroll: true });
  else currentEditor().focus();
}

function activeProjectPath() {
  return state.project?.path ?? null;
}

function requestContext(model = activeDocument()) {
  return captureDocumentContext(model, activeProjectPath());
}

function contextIsCurrent(context, options = {}) {
  return documentContextCurrent(
    context,
    {
      documents: state.documents,
      activeDocumentId: state.activeDocumentId,
      projectPath: activeProjectPath(),
    },
    options,
  );
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
  $$("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  $$("[data-i18n-placeholder]").forEach((element) => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });
  $$("[data-i18n-title]").forEach((element) => {
    const label = t(element.dataset.i18nTitle);
    element.title = label;
    if (element.matches("button")) element.setAttribute("aria-label", label);
  });
  $$("[data-i18n-aria-label]").forEach((element) => {
    element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel));
  });
  editorAdapter?.setAriaLabel?.(t("markdownEditor"));
  editorAdapter?.setLocale?.(state.locale, editorStrings());
  renderDocumentViewControls();
  const localeSetting = $("#setting-locale");
  if (localeSetting) localeSetting.value = state.locale;
  renderPresets();
  renderExportFiles();
  renderExportStatus();
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
  toggleWorkspaceLayoutMenu(false);
  if (name !== "export" && document.body.dataset.view === "export") void releaseEngineForJob();
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

/** Keep notifications in the setup column above the export controls. */
function syncExportToastPlacement() {
  if (document.body.dataset.view !== "export") return;
  const region = $("#toast-region");
  const dock = $("#export-view .export-dock");
  if (!region || !dock) return;
  const { left, right, top, width } = dock.getBoundingClientRect();
  const inlineStart = document.documentElement.dir === "rtl" ? window.innerWidth - right : left;
  region.style.setProperty("--export-toast-start", `${inlineStart}px`);
  region.style.setProperty("--export-toast-width", `${width}px`);
  if (getComputedStyle(dock).visibility === "hidden") {
    region.style.removeProperty("--export-toast-bottom");
    return;
  }
  region.style.setProperty(
    "--export-toast-bottom",
    `${Math.ceil(Math.max(12, window.innerHeight - top + 12))}px`,
  );
}

/**
 * Map a Markdown image path to a URL the webview may load.
 *
 * Only paths that resolve inside the open document's own directory are turned
 * into asset URLs; the native side grants a bounded inventory of image files.
 * HTTPS sources require an explicit host grant for this document session;
 * other remote and absolute sources remain outside the local asset scope.
 */
function resolveEditorAsset(source) {
  const online = safeOnlineImageURL(source);
  if (online)
    return onlineImageOrigins.get(activeDocument())?.has(new URL(online).origin) ? online : null;
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

function onlineImageOptions(model = activeDocument()) {
  const alts = documentImageAlts(model?.content);
  return {
    altFor: (source) => alts.get(source) || "",
    isAllowed(source) {
      const url = safeOnlineImageURL(source);
      return Boolean(url && onlineImageOrigins.get(model)?.has(new URL(url).origin));
    },
    onRequest(_origin, source) {
      const url = safeOnlineImageURL(source);
      if (!model || !state.documents.includes(model) || !url) return false;
      const origins = onlineImageOrigins.get(model) || new Set();
      origins.add(new URL(url).origin);
      onlineImageOrigins.set(model, origins);
      // Update sibling images from this host in every view of this document.
      // The grant lives only in this document's in-memory session.
      requestAnimationFrame(() => {
        if (activeDocument() !== model) return;
        editorAdapter?.refreshAssets?.();
        renderPreview(model);
      });
      return true;
    },
    strings: editorStrings(),
  };
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
  const model = activeDocument();
  const markdown = Boolean(model && isMarkdownModel(model));
  editorAdapter?.setMode?.(editorModeForView(mode));
  editorAdapter?.setReadOnly?.(
    !model ||
      model.readOnly ||
      mode === "read" ||
      state.updateInstalling ||
      Boolean(state.bookPreparing),
  );

  const showPreview = markdown && previewVisibleForView(mode, state.preferences.sidePreview);
  if (state.workspaceLayout.previewOpen !== showPreview) {
    state.workspaceLayout = { ...state.workspaceLayout, previewOpen: showPreview };
    applyWorkspaceLayout({ persist: true });
  }

  for (const button of $$("button[data-view-mode]")) {
    const selected = button.dataset.viewMode === mode;
    button.setAttribute("aria-checked", String(selected));
    button.tabIndex = selected ? 0 : -1;
    button.classList.toggle("selected", selected);
    button.disabled = !model || (!markdown && button.dataset.viewMode !== "source");
  }
  const sidePreview = $("#workspace-toggle-preview");
  if (sidePreview) {
    sidePreview.disabled = mode === "read" || !markdown;
    sidePreview.setAttribute("aria-pressed", String(showPreview));
  }
  $("#workspace-focus").disabled = !model;
  const surface = $(".editor-pane");
  if (surface) surface.dataset.viewMode = mode;
  if ($("#reading-surface")) $("#reading-surface").hidden = mode !== "read";
  if ($(".editor-surface")) $(".editor-surface").inert = !model || mode === "read";
  $("#workspace-view")?.setAttribute("data-view-mode", mode);
  updateAuthoringMode(model);
  if (markdown) loadFrontMatterForm(model);
  renderContentStatus();
}

function setViewMode(mode) {
  const previousMode = effectiveViewMode();
  if (activeDocument() && !isMarkdownModel(activeDocument()) && mode !== "source") return;
  if (mode === previousMode) return;
  const previousLine = previousMode === "read" ? readingSourceLine() : null;
  if (mode === "read" && previousMode !== "read" && activeDocument()) {
    pendingReadingLine = {
      id: activeDocument().id,
      line: editorAdapter?.firstVisibleLine?.() || 1,
    };
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
  else if (previousLine !== null)
    requestAnimationFrame(() => editorAdapter?.scrollToLine?.(previousLine));
  if (contentViewVisible()) schedulePreview(120, { entering: true });
  if (mode === "read") $("#reading-document")?.focus({ preventScroll: true });
  else editorAdapter?.focus?.();
}

function toggleSidePreview({ keepFocus = false } = {}) {
  updatePreference({ sidePreview: !state.preferences.sidePreview });
  if (contentViewVisible()) schedulePreview(120, { entering: true });
  if (!keepFocus) focusDocument();
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
  for (const autoPreview of $$("[data-content-auto]"))
    autoPreview.checked = Boolean(state.preferences.autoPreview);
}

function updatePreference(next, { persist = true } = {}) {
  state.preferences = { ...state.preferences, ...next };
  if (persist) state.preferences = writePreferences(state.preferences);
  applyInterfacePreferences();
}

function renderDocumentViewControls() {
  if ($("#writing-font")) $("#writing-font").value = state.preferences.writingFont;
  if ($("#writing-density")) $("#writing-density").value = state.preferences.writingDensity;
  for (const selector of ["#writing-font", "#writing-density"])
    if ($(selector)) $(selector).disabled = effectiveViewMode() === "source";
  if ($("#writing-zoom")) $("#writing-zoom").value = String(state.preferences.documentZoom);
  if ($("#writing-zoom-label"))
    $("#writing-zoom-label").textContent = `${state.preferences.documentZoom}%`;
  const zoom = state.preferences.documentZoom;
  const reset = $("#document-zoom-reset");
  if (reset) {
    reset.textContent = `${zoom}%`;
    reset.setAttribute(
      "aria-label",
      `${t("documentTextSize")}: ${zoom}%. ${t("resetDocumentZoom")}`,
    );
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
    $("#document-width-label").textContent = t(
      full
        ? "fullColumn"
        : state.preferences.writingWidth === "wide"
          ? "wideColumn"
          : "comfortableColumn",
    );
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
  updateDocumentView({
    documentZoom:
      direction === 0 ? 100 : nextDocumentZoom(state.preferences.documentZoom, direction),
  });
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
  consumeStartTab(model.id);
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
    section.classList.toggle(
      "hidden",
      Number(section.dataset.onboardingStep) !== state.onboardingStep,
    );
  });
  $$("[data-onboarding-dot]").forEach((dot) => {
    dot.classList.toggle("active", Number(dot.dataset.onboardingDot) <= state.onboardingStep);
  });
  $("#onboarding-back").classList.toggle("hidden", state.onboardingStep === 0);
  $("#onboarding-next").textContent = t(
    onboardingPrimaryActionKey(state.onboardingStep, state.onboardingIntent),
  );
  renderOnboardingIntent();
}

function openOnboarding({ force = false } = {}) {
  if (!force && state.preferences.onboardingComplete) return false;
  state.onboardingIntent = null;
  setOnboardingStep(0);
  modalManager.open($("#onboarding-modal"), {
    initialFocus: "[data-onboarding-action='document']",
  });
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
      ["bold", "bold", "pencil"],
      ["italic", "italic", "pencil"],
      ["strike", "strikethrough", "pencil"],
      ["link", "link", "link"],
      ["code", "code", "source"],
      ["bullet-list", "bulletList", "outline"],
      ["ordered-list", "orderedList", "outline"],
      ["task-list", "taskList", "quality"],
      ["quote", "blockQuote", "quote"],
      ["table", "insertTable", "table"],
      ["code-block", "codeBlock", "source"],
      ["callout", "insertCallout", "callout"],
      ["rule", "horizontalRule", "rule"],
    ].map(([command, label, symbol]) => ({
      id: `format-${command}`,
      symbol,
      label: t(label),
      keywords: `${command} markdown format قالب بندی`,
      priority: 45,
      enabled: canEdit,
      run: () => editorCommand(command),
    })),
    ...[1, 2, 3, 4, 5, 6].map((level) => ({
      id: `format-heading-${level}`,
      symbol: "outline",
      label: `${t("heading")} ${level}`,
      keywords: `heading h${level} عنوان`,
      priority: 43,
      enabled: canEdit,
      run: () => editorCommand(`heading-${level}`),
    })),
    {
      id: "insert-image",
      symbol: "image",
      label: t("insertImage"),
      keywords: "image photo تصویر عکس",
      priority: 45,
      enabled: canEdit,
      run: () => importAsset(),
    },
    {
      id: "quick-open",
      symbol: "folder",
      label: t("quickOpen"),
      keywords: "switch file document فایل سند",
      shortcut: "Ctrl P",
      priority: 94,
      run: () => navigationPicker.open("files"),
    },
    {
      id: "go-heading",
      symbol: "outline",
      label: t("goToHeading"),
      keywords: "heading outline section عنوان بخش",
      shortcut: "Ctrl Shift O",
      priority: 59,
      enabled: canRender,
      run: () => navigationPicker.open("headings"),
    },
    {
      id: "files-pane",
      symbol: "panel-left",
      label: t("toggleFiles"),
      keywords: "files explorer navigator فایل",
      priority: 38,
      run: () => toggleWorkspacePane("files"),
    },
    {
      id: "inspector-pane",
      symbol: "outline",
      label: t("toggleSidebar"),
      keywords: "outline inspector properties ساختار مشخصات",
      priority: 38,
      run: () => toggleWorkspacePane("sidebar"),
    },
    {
      id: "formatting-pane",
      symbol: "pencil",
      label: t("toggleFormatting"),
      keywords: "format toolbar tools قالب بندی",
      priority: 38,
      enabled: canEdit,
      run: () => toggleWorkspacePane("formatting"),
    },
    {
      id: "new",
      symbol: "plus",
      label: t("commandNewDocument"),
      keywords: "new document markdown",
      shortcut: "Ctrl N",
      priority: 100,
      run: () => createUntitledDocument(),
    },
    {
      id: "open",
      symbol: "file",
      label: t("commandOpenDocument"),
      keywords: "open file markdown",
      shortcut: "Ctrl O",
      priority: 95,
      run: () => chooseAuthoringFiles(),
    },
    {
      id: "project",
      symbol: "folder",
      label: t("commandOpenProject"),
      keywords: "open folder workspace project",
      priority: 80,
      run: () => chooseProjectDirectory(),
    },
    {
      id: "close-project",
      symbol: "close",
      label: t("closeProject"),
      keywords: "close project workspace folder",
      priority: 55,
      enabled: Boolean(state.project?.path),
      run: closeActiveProject,
    },
    {
      id: "book",
      symbol: "book",
      label: t("commandNewBook"),
      keywords: "book thesis chapters project",
      priority: 75,
      run: () => openNewBookModal(),
    },
    {
      id: "save",
      symbol: "save",
      label: t("commandSave"),
      keywords: "save write",
      shortcut: "Ctrl S",
      priority: 90,
      enabled: hasDocument,
      run: () => saveActiveDocument(),
    },
    {
      id: "save-as",
      symbol: "save-as",
      label: t("commandSaveAs"),
      keywords: "save as copy",
      shortcut: "Ctrl Shift S",
      priority: 70,
      enabled: hasDocument,
      run: () => saveActiveDocument({ saveAs: true }),
    },
    {
      id: "validate",
      symbol: "quality",
      label: t("commandValidate"),
      keywords: "check problems diagnostics",
      priority: 65,
      enabled: canRender,
      run: () => validateActiveDocument(),
    },
    {
      id: "export",
      symbol: "export",
      label: t("commandExport"),
      keywords: "pdf html word docx publish render خروجی",
      priority: 85,
      enabled: document.body.dataset.view !== "export",
      run: openWorkspaceExport,
    },
    {
      id: "export-file",
      symbol: "file",
      label: t("exportFile"),
      keywords: "export file external markdown",
      priority: 45,
      enabled: document.body.dataset.view !== "export",
      run: openFileExport,
    },
    {
      id: "find",
      symbol: "search",
      label: t("commandFind"),
      keywords: "find replace search",
      shortcut: "Ctrl F",
      priority: 60,
      enabled: hasDocument,
      run: () => openFind({ replace: false }),
    },
    {
      id: "settings",
      symbol: "settings",
      label: t("commandSettings"),
      keywords: "preferences appearance accessibility",
      priority: 40,
      run: () => openSettings(),
    },
    {
      id: "support-bundle",
      symbol: "archive",
      label: t("commandSupportBundle"),
      keywords: "support diagnostics troubleshooting zip privacy",
      priority: 38,
      run: () => saveSupportBundle(),
    },
    {
      id: "updates",
      symbol: "update",
      label: t("commandCheckUpdates"),
      keywords: "update upgrade release version",
      priority: 37,
      run: () => {
        openSettings("settings-updates");
        setTimeout(() => checkUpdates(), 0);
      },
    },
    // The constructs with no button of their own, so the palette can reach
    // them by name as well as the Insert menu by picture.
    {
      id: "insert-footnote",
      symbol: "footnote",
      label: t("insertFootnote"),
      keywords: "footnote note reference پانویس",
      priority: 46,
      enabled: canEdit,
      run: () => editorCommand("footnote"),
    },
    {
      id: "insert-math-inline",
      symbol: "maths",
      label: t("insertMathInline"),
      keywords: "math formula equation latex فرمول ریاضی",
      priority: 45,
      enabled: canEdit,
      run: () => editorCommand("math-inline"),
    },
    {
      id: "insert-math-block",
      symbol: "maths-block",
      label: t("insertMathBlock"),
      keywords: "math display block equation فرمول",
      priority: 44,
      enabled: canEdit,
      run: () => editorCommand("math-block"),
    },
    {
      id: "insert-diagram",
      symbol: "diagram",
      label: t("insertDiagram"),
      keywords: "mermaid diagram graph chart نمودار",
      priority: 43,
      enabled: canEdit,
      run: () => editorCommand("mermaid"),
    },
    {
      id: "insert-highlight",
      symbol: "highlight",
      label: t("insertHighlight"),
      keywords: "highlight mark هایلایت",
      priority: 43,
      enabled: canEdit,
      run: () => editorCommand("highlight"),
    },
    {
      id: "view-write",
      symbol: "pencil",
      label: t("viewWrite"),
      keywords: "write live formatted wysiwyg نوشتن",
      priority: 42,
      enabled: canRender,
      run: () => setViewMode("write"),
    },
    {
      id: "view-source",
      symbol: "source",
      label: t("viewSource"),
      keywords: "source raw markdown سورس",
      priority: 41,
      enabled: hasDocument,
      run: () => setViewMode("source"),
    },
    {
      id: "view-read",
      symbol: "book",
      label: t("viewRead"),
      keywords: "reading readonly خواندن مطالعه",
      priority: 41,
      enabled: canRender,
      run: () => setViewMode("read"),
    },
    {
      id: "view-split",
      symbol: "panel-right",
      label: t("sidePreview"),
      keywords: "split preview compare دوستونه پیش نمایش",
      priority: 40,
      enabled: canRender && effectiveViewMode() !== "read",
      run: toggleSidePreview,
    },
    {
      id: "view-guide",
      symbol: "help",
      label: t("viewGuide"),
      keywords: "view mode source read preview راهنمای نما",
      priority: 40,
      run: () => modalManager.open($("#view-guide-modal")),
    },
    {
      id: "typewriter",
      symbol: "typewriter",
      label: t("typewriterMode"),
      keywords: "typewriter scroll centre writing ماشین تحریر",
      priority: 39,
      run: () => updatePreference({ typewriter: !state.preferences.typewriter }),
    },
    {
      id: "focus-mode",
      symbol: "focus",
      label: t("focusMode"),
      keywords: "focus distraction free zen تمرکز",
      priority: 39,
      enabled: hasDocument,
      run: () => updatePreference({ focusMode: !state.preferences.focusMode }),
    },
    {
      id: "document-zoom-in",
      symbol: "zoom-in",
      label: t("increaseDocumentText"),
      keywords: "zoom text font larger اندازه متن بزرگ",
      shortcut: "Ctrl +",
      priority: 38,
      run: () => changeDocumentZoom(1),
    },
    {
      id: "document-zoom-out",
      symbol: "zoom-out",
      label: t("decreaseDocumentText"),
      keywords: "zoom text font smaller اندازه متن کوچک",
      shortcut: "Ctrl -",
      priority: 38,
      run: () => changeDocumentZoom(-1),
    },
    {
      id: "document-zoom-reset",
      symbol: "zoom-in",
      label: t("resetDocumentZoom"),
      keywords: "zoom text font reset اندازه متن",
      shortcut: "Ctrl 0",
      priority: 37,
      run: () => changeDocumentZoom(0),
    },
    {
      id: "document-full-width",
      symbol: "focus",
      label: t("useFullWidth"),
      keywords: "document width full canvas عرض تمام",
      priority: 37,
      run: () => updateDocumentView({ writingWidth: "full" }),
    },
    {
      id: "document-readable-width",
      symbol: "book",
      label: t("useReadableWidth"),
      keywords: "document width readable column عرض ستون خوانا",
      priority: 37,
      run: () => updateDocumentView({ writingWidth: "readable" }),
    },
    {
      id: "help",
      symbol: "help",
      label: t("commandHelp"),
      keywords: "help shortcuts guide onboarding",
      shortcut: "F1",
      priority: 35,
      run: () => openHelp(),
    },
  ];
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
  const payload = errorPayload(error);
  const code = payload?.application_code || payload?.data?.application_code || payload?.code;
  if (code === "MARDAS-OUTPUT-EXISTS") return t("outputExistsChooseNew");
  if (code === "MARDAS-OUTPUT-SIDECAR-UNSUPPORTED") return t("outputSidecarUnsupported");
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
const exportOptions = createExportOptionsPanel({
  root: $("#export-view"),
  t,
  getPresetOptions: () => presetById(state.presetId).options,
  onChange() {
    invalidateExportStatus();
    renderSummary();
    schedulePdfPreview();
  },
  pickPath: (field) =>
    invoke(field.widget === "directory" ? "pick_project_directory" : "pick_document_asset"),
  onError: (error) => toast(errorText(error), "error"),
});

function renderAdvancedOptions() {
  exportOptions.render();
}

function setExportSettingsOpen(open, { focus = true } = {}) {
  $("#export-setup").hidden = open;
  $("#export-settings").hidden = !open;
  $("#export-open-settings").setAttribute("aria-expanded", String(open));
  $("#export-close-settings").hidden = !open;
  const title = $("#export-inspector-title");
  title.dataset.i18n = open ? "documentSettings" : "exportSetup";
  title.textContent = t(title.dataset.i18n);
  if (focus) $(open ? "#option-search" : "#export-open-settings").focus({ preventScroll: true });
}

function setExportPane(pane) {
  $("#export-view").dataset.pane = pane;
  for (const button of $$("[data-export-pane]")) {
    button.setAttribute("aria-pressed", String(button.dataset.exportPane === pane));
  }
  syncExportToastPlacement();
}

function resetAdvancedOptions() {
  exportOptions.reset();
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
let exportPreviewDirty = false;
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
  if (exportPreviewTimer || exportPreviewFlight.isRunning) exportPreviewSequence += 1;
  if (exportPreviewTimer) {
    clearTimeout(exportPreviewTimer);
    exportPreviewTimer = null;
  }
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
  label.textContent = key ? t(key) : "";
  const retry = $("#export-preview-retry");
  if (key !== "previewFailedShort" && document.activeElement === retry)
    $("#export-preview-title").focus({ preventScroll: true });
  retry.hidden = key !== "previewFailedShort";
}

function setExportPreviewHasSource(hasSource) {
  const emptyState = $("#export-preview-empty");
  if (emptyState) emptyState.hidden = Boolean(hasSource);
  $("#export-preview")?.setAttribute("aria-hidden", String(!hasSource));
  $("#export-preview iframe")?.setAttribute("tabindex", hasSource ? "0" : "-1");
}

/** Put the export preview back into the interface language. */
function retranslateExportPreview() {
  setExportPreviewState(exportPreviewStateKey);
  renderPreviewNote(exportPreviewNotePayload);
  if (!pageDeck) return;
  // With no source there is nothing to ask the engine for; with one, the
  // sheet itself carries translated furniture and has to be drawn again.
  setExportPreviewHasSource(Boolean(state.sourcePath));
  $("#export-preview iframe")?.setAttribute("title", t("exportPreview"));
  if (!state.sourcePath) pageDeck.showMessage(t("previewChooseSource"));
  else schedulePdfPreview(0);
}

function schedulePdfPreview(delay = 450) {
  exportPreviewDirty = true;
  exportPreviewSequence += 1;
  if (exportPreviewTimer) clearTimeout(exportPreviewTimer);
  exportPreviewTimer = null;
  if (state.activeRequestId || document.body.dataset.view !== "export") return;
  if (state.sourcePath) setExportPreviewState("previewUpdating");
  exportPreviewTimer = setTimeout(() => {
    exportPreviewTimer = null;
    void exportPreviewFlight.run();
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
  const counter = $("#preview-page-count");
  const hasPages = Boolean(deckState.pageCount);
  if (level) level.textContent = hasPages ? `${Math.round((deckState.zoom || 1) * 100)}%` : "—";
  if (counter) {
    counter.textContent = deckState.pageCount
      ? `${deckState.currentPage} / ${deckState.pageCount}`
      : "—";
  }
  $("#preview-fit-width")?.setAttribute("aria-pressed", String(deckState.zoomMode === "fit-width"));
  $("#preview-fit-page")?.setAttribute("aria-pressed", String(deckState.zoomMode === "fit-page"));
  $("#preview-guides")?.setAttribute("aria-pressed", String(Boolean(deckState.guides)));
  for (const id of [
    "#preview-zoom-out",
    "#preview-zoom-in",
    "#preview-fit-width",
    "#preview-fit-page",
    "#preview-guides",
  ]) {
    const button = $(id);
    if (button) button.disabled = !hasPages;
  }
  for (const [id, atEnd] of [
    ["#preview-prev-page", deckState.currentPage <= 1],
    ["#preview-next-page", deckState.currentPage >= deckState.pageCount],
  ]) {
    const button = $(id);
    button.disabled = !hasPages;
    button.setAttribute("aria-disabled", String(!hasPages || atEnd));
  }
}

function movePreviewPage(delta) {
  if (
    $(delta < 0 ? "#preview-prev-page" : "#preview-next-page").getAttribute("aria-disabled") ===
    "true"
  )
    return;
  const deck = exportPreviewDeck();
  if (!deck?.pageCount) return;
  const counter = $("#preview-page-count");
  const current =
    Number(
      String(counter?.textContent || "1")
        .split("/")[0]
        .trim(),
    ) || 1;
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
  if (payload) lines.push(t("previewPaginationApproximate"));
  if (payload?.degraded) lines.push(t("previewEngineOutdated"));
  note.hidden = lines.length === 0;
  $("#export-preview-note-copy").textContent = lines.join(" · ");
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
async function drawExportPreview() {
  if (state.activeRequestId || document.body.dataset.view !== "export") return;
  const deck = exportPreviewDeck();
  if (!deck) return;
  setExportPreviewHasSource(Boolean(state.sourcePath));
  if (!state.sourcePath) {
    exportPreviewDirty = false;
    setExportPreviewState("");
    renderPreviewNote(null);
    deck.showMessage(t("previewChooseSource"));
    return;
  }
  const sequence = exportPreviewSequence;
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
    // Layout and MathJax run in the webview. They must not keep the engine
    // flight occupied when the user changes files or starts a PDF job.
    void paintExportPreview(deck, result, sequence);
  } catch (error) {
    failExportPreview(deck, sequence, error);
  } finally {
    if (exportPreviewRequestId === id) exportPreviewRequestId = null;
  }
}

function exportPreviewIsCurrent(sequence) {
  return sequence === exportPreviewSequence && document.body.dataset.view === "export";
}

async function paintExportPreview(deck, result, sequence) {
  try {
    await deck.render(result, { isCurrent: () => exportPreviewIsCurrent(sequence) });
    if (!exportPreviewIsCurrent(sequence)) return;
    exportPreviewDirty = false;
    renderPreviewNote(result);
    setExportPreviewState("");
  } catch (error) {
    failExportPreview(deck, sequence, error);
  }
}

function failExportPreview(deck, sequence, error) {
  if (!exportPreviewIsCurrent(sequence)) return;
  exportPreviewDirty = false;
  setExportPreviewState("previewFailedShort");
  const payload = errorPayload(error);
  renderPreviewNote(null);
  deck.showMessage(payload?.message || t("previewFailed"), diagnosticLines(payload));
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
  return exportOptions.overrides();
}

function renderPresets() {
  const select = $("#export-preset");
  select.replaceChildren(
    ...Object.values(PRESETS).map((preset) => new Option(t(preset.titleKey), preset.id)),
  );
  select.value = state.presetId;
}

/**
 * Apply a preset by seeding the settings panel with its values.
 *
 * The preset is a starting point the user can then adjust in place, so its
 * choices have to be visible in the same controls they would use to change
 * them.
 */
function selectPreset(id) {
  invalidateExportStatus();
  const preset = presetById(id);
  state.presetId = preset.id;
  $("#export-preset").value = preset.id;
  exportOptions.reset();
}

function renderSummary() {
  const container = $("#preset-summary");
  const preset = presetById(state.presetId);
  const options = exportOverrides();
  const changed = exportOptions.modifiedCount();
  $("#export-preset-help").textContent = t(preset.descriptionKey);
  const count = $("#export-change-count");
  count.hidden = changed === 0;
  count.textContent = changed ? `${changed} ${t("changedCount")}` : "";
  const rows = [
    [t("pageSize"), options.page_size ?? t("inherit")],
    [t("toc"), options.toc === undefined ? t("inherit") : t(options.toc ? "enabled" : "disabled")],
    [
      t("quality"),
      options.quality_profile === undefined
        ? t("inherit")
        : t(options.quality_profile === "strict-publication" ? "strict" : "standard"),
    ],
  ];
  container.replaceChildren(
    ...rows.map(([label, value]) => {
      const row = document.createElement("div");
      row.className = "summary-row";
      const caption = document.createElement("dt");
      caption.textContent = label;
      const detail = document.createElement("dd");
      setTruncatableText(detail, value);
      row.append(caption, detail);
      return row;
    }),
  );
}

function renderRecents() {
  const list = $("#recent-list");
  if (!list) return;
  list.replaceChildren();
  $("#recent-empty").hidden = state.recents.length > 0;
  $("#clear-recents").hidden = state.recents.length === 0;
  for (const recent of state.recents) {
    const button = document.createElement("button");
    button.className = "recent-item";
    button.type = "button";
    button.innerHTML = `<span class="recent-icon" aria-hidden="true"></span><span class="recent-copy"><strong></strong><small></small></span>`;
    button.querySelector(".recent-icon").append(spriteIcon("file"));
    setTruncatableText(button.querySelector("strong"), basename(recent.path));
    setTruncatableText(button.querySelector("small"), compactDocumentLocation(recent.path));
    button.querySelector("small").title = recent.path;
    button.title = recent.path;
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
  $("#export-result").hidden = true;
}

function showExportResult(path) {
  const resultPath = String(path || "").trim();
  const container = $("#export-result");
  if (!resultPath) return;
  container.title = resultPath;
  container.hidden = false;
}

function openExportFormat(onPdf, { book = false, returnFocus } = {}) {
  const dialog = $("#export-format-modal");
  if (modalManager.isOpen(dialog)) return;
  const title = $("#export-format-title");
  const titleKey = book ? "exportBook" : "commandExport";
  title.dataset.i18n = titleKey;
  title.textContent = t(titleKey);
  const pdfButton = $("#export-format-pdf");
  pdfButton.onclick = async () => {
    modalManager.close(dialog);
    try {
      await onPdf();
    } catch (error) {
      toast(errorText(error), "error");
    }
  };
  modalManager.open(dialog, {
    initialFocus: pdfButton,
    returnFocus,
    onClose: () => {
      pdfButton.onclick = null;
    },
  });
}

function openFileExport() {
  openExportFormat(() => openExportSource(""));
}

function openWorkspaceExport() {
  const model = activeDocument();
  const intent = state.documentActivationSequence;
  openExportFormat(
    () => {
      if (!model || !isMarkdownModel(model)) return openExportSource("");
      if (intent !== state.documentActivationSequence || activeDocument()?.id !== model.id) {
        toast(t("exportDocumentChanged"), "warning");
        return;
      }
      return exportActiveDocument();
    },
    { returnFocus: $("#workspace-export") },
  );
}

function renderExportFiles() {
  for (const [kind, path] of [
    ["source", state.sourcePath],
    ["output", state.outputPath],
  ]) {
    const input = $(`#${kind}-path`);
    input.value = path;
    input.title = path;
    input.closest(".export-file").dataset.selected = String(Boolean(path));
    setTruncatableText($(`#export-${kind}-name`), basename(path));
  }
  const choose = $("#choose-source");
  choose.classList.toggle("primary", !state.sourcePath);
  choose.classList.toggle("secondary", Boolean(state.sourcePath));
  choose.dataset.i18n = state.sourcePath ? "exportChange" : "exportChooseFile";
  choose.textContent = t(choose.dataset.i18n);
  if (state.sourcePath) choose.setAttribute("aria-label", t("exportChangeSource"));
  else choose.removeAttribute("aria-label");
  syncExportControls();
}

function openExportSource(path) {
  if (state.activeRequestId) return;
  const entering = document.body.dataset.view !== "export";
  hideExportResult();
  if (entering || state.sourcePath !== path) {
    exportPreviewSequence += 1;
    setExportPreviewState("");
    renderPreviewNote(null);
    pageDeck?.showMessage(t(path ? "previewUpdating" : "previewChooseSource"));
  }
  state.sourcePath = path;
  state.outputPath = defaultOutputPath(path);
  renderExportFiles();
  setExportPreviewHasSource(Boolean(path));
  setExportStatus("idle");
  if (entering) {
    setExportPane("setup");
    setExportSettingsOpen(false, { focus: false });
    $("#export-setup").scrollTop = 0;
    showView("export");
    $(path ? "#export-title" : "#choose-source").focus({ preventScroll: true });
  }
  schedulePdfPreview(path ? 120 : 0);
}

async function chooseExportSource(event) {
  try {
    const fromPreview = event.currentTarget.id === "preview-choose-source";
    const path = await invoke("pick_markdown_file");
    if (!path || state.activeRequestId || document.body.dataset.view !== "export") return;
    openExportSource(path);
    $(fromPreview ? "#export-preview-title" : "#choose-source").focus({ preventScroll: true });
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
    const path = await invoke("pick_pdf_output", {
      suggested_path: state.outputPath || defaultOutputPath(state.sourcePath),
    });
    if (path) {
      state.outputPath = path;
      renderExportFiles();
      invalidateExportStatus();
    }
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function exportSelectionValid() {
  const errors = validateExportSelection({
    sourcePath: state.sourcePath,
    outputPath: state.outputPath,
  });
  if (!errors.length) return true;
  setExportStatus("error", "errorTitle", { message: errors.map((code) => t(code)).join(" ") });
  if (errors.some((code) => code === "source_required" || code === "source_markdown")) {
    setExportPane("setup");
    setExportSettingsOpen(false, { focus: false });
    $("#choose-source").focus();
  } else if (
    errors.some(
      (code) => code === "output_required" || code === "output_pdf" || code === "paths_differ",
    )
  ) {
    $("#choose-output").focus();
  }
  return false;
}

// ---------------------------------------------------------------------------
// Authoring workspace
// ---------------------------------------------------------------------------
function persistSession() {
  writeSession(state.documents, activeDocument(), state.project?.path ?? null);
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
  const position =
    editorAdapter?.lineAtOffset?.() ||
    textMetrics(model?.content || "", currentEditor().selectionStart);
  const metrics = documentMetrics(model, position);
  $("#cursor-status").textContent =
    `${t("lineShort")} ${metrics.line}, ${t("columnShort")} ${metrics.column}`;
  $("#word-status").textContent =
    `${metrics.words} ${t("wordsLabel")} · ${metrics.characters} ${t("charactersLabel")}`;
  outlineNavigator?.setActiveLine(metrics.line, { scroll: true });
  updateFormattingState();
}

function updateFormattingState() {
  const flags = editorAdapter?.getFormattingState?.() || {};
  for (const button of $$("[data-editor-command]")) {
    const command = button.dataset.editorCommand;
    if (Object.hasOwn(flags, command) && typeof flags[command] === "boolean")
      button.setAttribute("aria-pressed", String(flags[command]));
    else button.removeAttribute("aria-pressed");
  }
}

function renderOutline(model) {
  const outline = extractOutline(model?.content || "");
  $("#outline-count").textContent = String(outline.length);
  if (!outlineNavigator)
    outlineNavigator = createOutlineNavigator({
      container: $("#outline-list"),
      onNavigate: (line) => goToLine(line),
    });
  if (outlineLocale !== state.locale) {
    outlineLocale = state.locale;
    outlineNavigator.setLabels({
      empty: t("noOutline"),
      noMatches: t("noOutlineMatches"),
      label: t("documentOutline"),
      expand: t("expandOutline"),
      collapse: t("collapseOutline"),
    });
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
    const present = rawLines.some((line) =>
      new RegExp(`^(?:${name}|"${name}"|'${name}'):`).test(line),
    );
    const structured =
      present &&
      (value === undefined ||
        (value !== null && typeof value === "object") ||
        /[\r\n]/.test(String(value ?? "")) ||
        (input instanceof HTMLSelectElement &&
          value !== undefined &&
          ![...input.options].some((option) => option.value === String(value))));
    input.value = structured ? "" : (value ?? (name === "lang" || name === "dir" ? "auto" : ""));
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
  $("#structured-metadata-note")?.classList.toggle(
    "hidden",
    !(hasStructuredFields || tocStructured),
  );
}

function renderCitations(model) {
  const used = extractCitationKeys(model?.content || "");
  if (state.project?.path && model?.projectPath === state.project.path) {
    renderBibliographyEntries(state.bibliographyEntries, used);
    return;
  }
  const entries = Array.isArray(model?.preview?.document?.citation_entries)
    ? model.preview.document.citation_entries
    : [];
  const entryKeys = entries
    .map((entry) => entry.key || entry.id || entry.citation_key)
    .filter(Boolean);
  const keys = [...new Set([...used, ...entryKeys])].sort((a, b) =>
    String(a).localeCompare(String(b)),
  );
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
    button.querySelector("small").textContent = t(
      used.includes(key) ? "cited" : "bibliographyLibrary",
    );
    button.addEventListener("click", () => insertAtCursor(`[@${key}]`));
    list.append(button);
  }
}

function renderProblems(model) {
  const entries = [
    ...(Array.isArray(model?.diagnostics)
      ? model.diagnostics.map((item) => ({ item, scope: "document" }))
      : []),
    ...(Array.isArray(model?.bibliographyDiagnostics)
      ? model.bibliographyDiagnostics.map((item) => ({ item, scope: "document" }))
      : []),
    ...(state.project?.path && Array.isArray(state.projectDiagnostics)
      ? state.projectDiagnostics.map((item) => ({ item, scope: "project" }))
      : []),
  ];
  const seen = new Set();
  const distinct = entries.filter(({ item }) => {
    const key = JSON.stringify([item.code, item.path, item.line, item.column, item.message]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const diagnostics = distinct.map(({ item }) => item);
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
    const pending =
      isMarkdownModel(model) &&
      model?.validationContentVersion !== model?.contentVersion &&
      model?.previewContentVersion !== model?.contentVersion;
    const note = document.createElement("div");
    note.className = "tool-empty";
    note.textContent = t(pending ? "contentChecksPending" : "noProblems");
    list.append(note);
    return;
  }
  for (const { item: diagnostic, scope } of distinct) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tool-item problem-${diagnostic.severity || "info"}`;
    button.innerHTML = `<span class="level"></span><span></span>`;
    button.querySelector(".level").textContent = diagnostic.code || "!";
    const label = scope === "project" ? t("projectDiagnosticScope") : t("documentDiagnosticScope");
    button.querySelector("span:last-child").textContent = [
      label,
      diagnostic.path,
      diagnostic.message || String(diagnostic),
    ]
      .filter(Boolean)
      .join(" · ");
    if (scope === "project" && diagnostic.path && state.project?.path) {
      button.addEventListener("click", () =>
        openProjectRelativeFile(diagnostic.path, {
          line: diagnostic.line || 1,
          column: diagnostic.column || 1,
        }),
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
    button.querySelector(".asset-kind").textContent = String(asset.extension || "file").replace(
      ".",
      "",
    );
    button.querySelector("span:last-child").textContent = asset.relative_path || asset.name;
    button.addEventListener("click", () => insertAssetReference(asset));
    list.append(button);
  }
}

function updateAuthoringMode(model) {
  const hasDocument = Boolean(model);
  $("#workspace-view").dataset.empty = String(!hasDocument);
  document.documentElement.dataset.focusMode = String(hasDocument && state.preferences.focusMode);
  $(".document-toolbar").inert = !hasDocument;
  const markdown = isMarkdownModel(model);
  editorAdapter?.setAriaLabel?.(t(markdown ? "markdownEditor" : "textResourceEditor"));
  const editable =
    hasDocument &&
    !model.readOnly &&
    !state.updateInstalling &&
    !state.bookPreparing &&
    effectiveViewMode() !== "read";
  $("#workspace-save").disabled = !hasDocument || model.readOnly;
  $("#workspace-save-as").disabled = !hasDocument;
  for (const element of $$(
    "[data-editor-command], #workspace-import-asset, #import-asset, #refresh-assets",
  )) {
    element.disabled = !editable || !markdown;
  }
  for (const selector of [
    "#workspace-validate",
    "#refresh-preview",
    "#auto-preview",
    "#refresh-reading",
    "#reading-auto-preview",
  ]) {
    $(selector).disabled = !hasDocument || !markdown;
  }
  for (const name of ["outline", "frontmatter", "assets", "citations"]) {
    const button = $(`[data-sidebar="${name}"]`);
    if (button) button.disabled = !hasDocument || !markdown;
  }
  applySidebarContext();
  $("#frontmatter-form")
    ?.querySelectorAll("input,select,button")
    .forEach((element) => {
      element.disabled = !editable || !markdown;
    });
  $("#workspace-view")?.classList.toggle("plain-text-mode", hasDocument && !markdown);
  $("#insert-menu-button").disabled = !editable || !markdown;
  $("#workspace-toggle-formatting")?.toggleAttribute("disabled", !editable || !markdown);
  editorAdapter?.setReadOnly?.(
    !model ||
      model.readOnly ||
      effectiveViewMode() === "read" ||
      state.updateInstalling ||
      Boolean(state.bookPreparing),
  );
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
  return Object.fromEntries(
    [
      "imageNotFound",
      "remoteImageNotLoaded",
      "loadRemoteImages",
      "remoteImageLoading",
      "remoteImageFailed",
      "retryRemoteImage",
      "remoteImageBlocked",
    ].map((key) => [key, t(key)]),
  );
}

function bindEditorHistoryShortcuts(adapter) {
  if (adapter?.kind !== "codemirror" || !adapter.element) return;
  adapter.element.addEventListener(
    "keydown",
    (event) => {
      if (event.defaultPrevented || event.altKey || !(event.ctrlKey || event.metaKey)) return;
      const key = event.key.toLowerCase();
      const command =
        key === "z"
          ? event.shiftKey
            ? "redo"
            : "undo"
          : key === "y" && !event.shiftKey
            ? "redo"
            : null;
      const succeeded = command ? adapter.runCommand(command) : false;
      if (succeeded) {
        event.preventDefault();
        event.stopPropagation();
      }
    },
    { capture: true },
  );
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
  if (model) state.activeStartTabId = null;
  $("#workspace-empty-title").textContent = t(state.activeStartTabId ? "newTab" : "noDocumentOpen");
  renderDocumentTabs();
  requestAnimationFrame(revealActiveTab);
  const editor = currentEditor();
  editor.retainDocuments?.(state.documents.map((document) => document.id));
  renderProjectWorkspace();
  renderBookWorkspace();
  if (!model) {
    closeFind({ restoreFocus: false });
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
  if (editor.setDocument)
    editor.setDocument(model.id, model.content, {
      initialSelection: bodyStartOffset(model.content),
      kind: isMarkdownModel(model) ? "markdown" : "text",
    });
  else if (editor.value !== model.content) editor.value = model.content;
  if (!$("#find-bar").classList.contains("hidden")) updateFindMatches();
  else editorAdapter?.setSearchMatches?.();
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
    if (
      granted?.path === model.path &&
      sources.length === granted.sources.size &&
      sources.every((source) => granted.sources.has(source))
    )
      return;
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
  state.activeStartTabId = null;
  state.validationSequence += 1;
  state.assetSequence += 1;
  state.bibliographySequence += 1;
  persistSession();
  renderWorkspace();
  if (focus === "tab") {
    const tab = $$(".document-tab").find((element) => element.dataset.documentId === id);
    tab?.querySelector(".tab-activate")?.focus();
  } else if (effectiveViewMode() === "read") $("#reading-document")?.focus({ preventScroll: true });
  else currentEditor().focus();
  schedulePreview(80, { entering: true });
  if (model.path) refreshAssets();
}

function consumeStartTab(replacementId, { moveExisting = false } = {}) {
  if (!state.activeStartTabId) return;
  const startId = state.activeStartTabId;
  if (replacementId && (moveExisting || !state.tabOrder.includes(replacementId))) {
    state.tabOrder = state.tabOrder
      .filter((id) => id !== replacementId)
      .map((id) => (id === startId ? replacementId : id));
  } else {
    state.tabOrder = state.tabOrder.filter((id) => id !== startId);
  }
  state.startTabs = state.startTabs.filter((tab) => tab.id !== state.activeStartTabId);
  state.activeStartTabId = null;
}

function activateStartTab(id, focus = "editor") {
  if (!state.startTabs.some((tab) => tab.id === id)) return;
  if (activeDocument() && editorAdapter?.commitPendingDrafts?.() === false) return;
  state.documentActivationSequence += 1;
  state.activeDocumentId = null;
  state.activeStartTabId = id;
  persistSession();
  renderWorkspace();
  if (focus === "tab") {
    $$(".document-tab")
      .find((tab) => tab.dataset.documentId === id)
      ?.querySelector(".tab-activate")
      ?.focus();
  } else focusDocument();
}

function createStartTab() {
  if (activeDocument() && editorAdapter?.commitPendingDrafts?.() === false) return;
  const tab = {
    id:
      globalThis.crypto?.randomUUID?.() ??
      `start-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    isStart: true,
  };
  state.startTabs.push(tab);
  state.tabOrder.push(tab.id);
  activateStartTab(tab.id);
}

function closeStartTab(id) {
  const wasActive = state.activeStartTabId === id;
  if (wasActive) state.documentActivationSequence += 1;
  state.startTabs = state.startTabs.filter((tab) => tab.id !== id);
  if (!wasActive) {
    renderDocumentTabs();
  } else if (state.startTabs.length) {
    activateStartTab(state.startTabs.at(-1).id);
  } else if (state.documents.length) {
    state.activeStartTabId = null;
    void activateDocument(state.documents.at(-1).id);
  } else {
    state.activeStartTabId = null;
    renderWorkspace();
    focusDocument();
  }
}

function createUntitledDocument() {
  state.documentActivationSequence += 1;
  if (state.preferences.viewMode === "read") updatePreference({ viewMode: "write" });
  const model = createDocument({ content: "" });
  consumeStartTab(model.id);
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
  let intendedWasNew = false;
  showView("workspace");
  for (const path of values) {
    const existing = findDocumentByPath(state.documents, path);
    if (existing) {
      await allowDocumentImages(existing);
      if (state.documents.includes(existing)) {
        intendedDocument = existing;
        intendedWasNew = false;
      }
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
      const model =
        duplicate ||
        createDocument({
          path: result.path,
          content: result.content,
          revision: result.revision,
          readOnly: result.read_only,
          kind: result.kind || (isMarkdownPath(result.path) ? "markdown" : "text"),
        });
      attachProjectMembership(model, state.project);
      if (!duplicate) state.documents.push(model);
      await allowDocumentImages(model);
      if (state.documents.includes(model)) {
        intendedDocument = model;
        intendedWasNew = !duplicate;
      }
      saveRecent(model.path);
      const recovery = recoveryForPath(model.path);
      if (
        sequence === state.documentActivationSequence &&
        state.documents.includes(model) &&
        recovery &&
        recovery.content !== model.content
      )
        showRecovery(model, recovery);
    } catch (error) {
      toast(errorText(error), "error");
    }
  }
  // Keep the owner of the visible buffer unchanged throughout every file read
  // and scope grant, including when several files are opened together.
  if (sequence === state.documentActivationSequence && state.documents.includes(intendedDocument)) {
    consumeStartTab(intendedDocument.id, { moveExisting: intendedWasNew });
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

async function openProjectRelativeFile(relativePath, { line = null, column = 1 } = {}) {
  const projectPath = state.project?.path;
  const projectGeneration = state.projectGeneration;
  if (!projectPath) return;
  const sequence = ++state.documentActivationSequence;
  try {
    const requestKey = `${projectGeneration}:${relativePath}`;
    let request = state.projectFileRequests.get(requestKey);
    if (!request) {
      request = readProjectFile(projectPath, relativePath).finally(() =>
        state.projectFileRequests.delete(requestKey),
      );
      state.projectFileRequests.set(requestKey, request);
    }
    const result = await request;
    if (state.project?.path !== projectPath || state.projectGeneration !== projectGeneration)
      return;
    if (sequence !== state.documentActivationSequence) return;
    const existing = findDocumentByPath(state.documents, result.absolute_path);
    let model = existing;
    const file = state.project.files?.find(
      (item) => item.path === result.path || item.path === relativePath,
    );
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
    if (
      sequence !== state.documentActivationSequence ||
      !state.documents.includes(model) ||
      state.project?.path !== projectPath ||
      state.projectGeneration !== projectGeneration
    )
      return;
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
      markDocumentSaved(
        model,
        {
          path: result.absolute_path,
          revision: result.revision,
          read_only: result.read_only,
        },
        result.content,
      );
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

function applyProjectPayload(payload) {
  const project = payload?.project || payload;
  if (!project?.path) return null;
  if (pathKey(project.path) !== pathKey(state.project?.path)) {
    invalidateBookTaskForProjectChange();
    state.bookOutputPath = null;
  }
  applyProjectSession(state, project);
  persistSession();
  renderProjectWorkspace();
  renderBookWorkspace();
  renderProblems(activeDocument());
  return project;
}

function clearProjectState() {
  const bookHandoff = invalidateBookTaskForProjectChange();
  const searchHandoff = cancelActiveProjectSearch({ announce: false });
  resetProjectSession(state);
  updateAuthoringMode(activeDocument());
  persistSession();
  renderProjectWorkspace();
  renderBookWorkspace();
  renderCitations(activeDocument());
  renderProblems(activeDocument());
  renderWorkspace();
  void refreshAssets();
  return Promise.allSettled([bookHandoff, searchHandoff]);
}

function closeActiveProject() {
  if (!state.project?.path) return;
  const projectName = state.project.name || t("projectWorkspace");
  // Detach the UI and preserve open documents immediately. Search/book
  // cancellation can take a round trip through the engine, but a project
  // close should never feel like a hung command while that handoff completes.
  const cleanup = clearProjectState();
  showView("workspace");
  activateSidebar("project");
  $("#sidebar-open-project")?.focus({ preventScroll: true });
  toast(`${t("projectClosed")}: ${projectName}`, "success");
  return cleanup;
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
  $("#close-book-project").hidden = !enabled;
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
  $("#book-current-chapter").textContent =
    activeIndex >= 0 ? `${activeIndex + 1}/${chapters.length}` : "—";
  list.replaceChildren(
    ...chapters.map((chapter, index) => bookChapterRow(chapter, index, chapters)),
  );
  renderBookOutputResult();
  syncBookOperationControls();
}

function bibliographyEntryAuthors(entry) {
  const authors = Array.isArray(entry?.authors) ? entry.authors : [];
  return authors
    .map((author) => author.display || [author.family, author.given].filter(Boolean).join(", "))
    .filter(Boolean)
    .join("; ");
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
    row.querySelector("small").textContent = [bibliographyEntryAuthors(entry), entry.year]
      .filter(Boolean)
      .join(" · ");
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
      model.bibliographyDiagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
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
  $("#recovery-message").textContent =
    `${t("recoveryMessage")} ${formatMoment(recovery.updatedAt)}`;
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

function renderContentStatus() {
  const model = activeDocument();
  const stale = Boolean(model?.preview && model.previewContentVersion !== model.contentVersion);
  const label = stale
    ? t("contentPreviewStale")
    : !state.preferences.autoPreview
      ? t("contentPreviewPaused")
      : t("contentPreviewScope");
  for (const status of $$("[data-content-status]")) {
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
let pendingMarkdownLinkNavigation = null;
let markdownLinkSequence = 0;

function applyPendingMarkdownLinkNavigation(container, model, { announceMissing = false } = {}) {
  const pending = pendingMarkdownLinkNavigation;
  if (!pending || !model?.path || pathKey(model.path) !== pending.pathKey) return false;
  if (!pending.fragment) {
    pendingMarkdownLinkNavigation = null;
    return true;
  }
  const target = [...container.querySelectorAll("[data-preview-source-id]")].find(
    (element) => element.dataset.previewSourceId === pending.fragment,
  );
  if (!target) {
    if (announceMissing) {
      pendingMarkdownLinkNavigation = null;
      toast(t("linkedHeadingMissing"), "warning");
    }
    return false;
  }
  pendingMarkdownLinkNavigation = null;
  target.scrollIntoView({ block: "start", behavior: "smooth" });
  if (effectiveViewMode() !== "read") {
    const line = Number(target.dataset.sourceLine);
    if (line > 0) goToLine(line);
  }
  return true;
}

function contentAnchors(container, model) {
  const frame = container.getBoundingClientRect();
  const anchors = [{ line: 1, top: 0 }];
  for (const heading of container.querySelectorAll(
    "h1[data-source-line],h2[data-source-line],h3[data-source-line],h4[data-source-line],h5[data-source-line],h6[data-source-line]",
  )) {
    const line = Number(heading.dataset.sourceLine);
    if (line > anchors.at(-1).line)
      anchors.push({
        line,
        top: heading.getBoundingClientRect().top - frame.top + container.scrollTop,
      });
  }
  anchors.push({ line: model.content.split("\n").length + 1, top: container.scrollHeight });
  return anchors;
}

function readingSourceLine() {
  const container = $("#reading-document");
  const model = activeDocument();
  return model && container
    ? Math.round(
        interpolatePosition(contentAnchors(container, model), container.scrollTop, "top", "line"),
      )
    : 1;
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
    sanitize: safePreviewHtml,
    prefix: "reading-",
    sourceEntries: previewSourceEntries(model),
    onlineImages: onlineImageOptions(model),
    blockedImageLabel: (reason) =>
      t(reason === "remote" ? "remoteImageNotLoaded" : "imageBlockedOrMissing"),
  });
  container.scrollTop = previousScroll;
  applyPendingMarkdownLinkNavigation(container, model);
  const current = () => activeDocument()?.id === model.id && model.preview === payload;
  return typesetPreviewMath(container, {
    isCurrent: current,
    errorLabel: t("previewMathFailed"),
  }).then(() => {
    if (current() && pendingReadingLine?.id === model.id) {
      container.scrollTop = interpolatePosition(
        contentAnchors(container, model),
        pendingReadingLine.line,
      );
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
  container
    .querySelectorAll(".source-active")
    .forEach((element) => element.classList.remove("source-active"));
  const target =
    container.querySelector(`#${CSS.escape(`preview-${active.id}`)}`) ||
    container.querySelector(`[data-source-line="${active.line}"]`);
  if (!target) return;
  target.classList.add("source-active");
  if (center && !state.previewSyncing) {
    state.previewSyncing = true;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    setTimeout(() => {
      state.previewSyncing = false;
    }, 180);
  }
}

function syncPreviewFromEditorScroll(scrollTop) {
  const editorElement = editorAdapter?.element || $("#markdown-editor");
  if (!editorElement || state.previewSyncing) return;
  // Wrapped rows and Markdown widgets do not correspond one-for-one with
  // source lines. The textarea fallback has no measured document map.
  const lineHeight = Number.parseFloat(getComputedStyle(editorElement).lineHeight) || 24;
  const visibleLine =
    editorAdapter?.firstVisibleLine?.() ??
    Math.max(1, Math.floor((Number(scrollTop) || 0) / lineHeight) + 1);
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
    sanitize: safePreviewHtml,
    sourceEntries: previewSourceEntries(model),
    onlineImages: onlineImageOptions(model),
    onSourceJump: (line) => goToLine(line),
    sourceJumpLabel: (line) => `${t("goToSourceLine")} ${line}`,
    blockedImageLabel: (reason) =>
      t(reason === "remote" ? "remoteImageNotLoaded" : "imageBlockedOrMissing"),
  });
  syncPreviewFromEditorScroll(currentEditor().scrollTop || 0);
  applyPendingMarkdownLinkNavigation(container, model);
  return typesetPreviewMath(container, {
    isCurrent: () => activeDocument()?.id === model.id && model.preview === payload,
    errorLabel: t("previewMathFailed"),
  });
}

async function activateMarkdownDocumentLink(event) {
  const link = event.target?.closest?.("a[data-mardas-markdown-href]");
  const container = event.currentTarget;
  if (!link || !container?.contains(link)) return;
  event.preventDefault();
  if (link.dataset.opening === "true") return;
  const model = activeDocument();
  if (!model?.path || !isMarkdownModel(model)) {
    toast(t("linkedMarkdownNeedsSave"), "warning");
    return;
  }
  const sequence = ++markdownLinkSequence;
  link.dataset.opening = "true";
  const projectPath =
    model.projectPath &&
    state.project?.path &&
    pathKey(model.projectPath) === pathKey(state.project.path)
      ? state.project.path
      : undefined;
  try {
    const resolved = await resolveMarkdownLink(
      model.path,
      link.dataset.mardasMarkdownHref,
      projectPath,
    );
    if (sequence !== markdownLinkSequence || activeDocument()?.id !== model.id) return;
    pendingMarkdownLinkNavigation = {
      pathKey: pathKey(resolved.path),
      fragment: String(resolved.fragment || ""),
      sequence,
    };
    if (pathKey(resolved.path) === pathKey(model.path)) {
      if (!applyPendingMarkdownLinkNavigation(container, model)) {
        await refreshPreview();
        if (sequence !== markdownLinkSequence || activeDocument()?.id !== model.id) return;
        applyPendingMarkdownLinkNavigation(container, model, { announceMissing: true });
      }
      return;
    }

    if (container.id === "book-review-document") {
      modalManager.close($("#book-review-modal"));
    }
    if (projectPath && resolved.relative_path) {
      await openProjectRelativeFile(resolved.relative_path);
    } else {
      const existing = findDocumentByPath(state.documents, resolved.path);
      if (existing) await activateDocument(existing.id);
      else await openAuthoringPaths([resolved.path]);
    }
    if (sequence !== markdownLinkSequence) return;
    const targetDocument = activeDocument();
    if (!targetDocument?.path || pathKey(targetDocument.path) !== pathKey(resolved.path)) {
      pendingMarkdownLinkNavigation = null;
      return;
    }
    if (resolved.fragment) {
      await refreshPreview();
      if (sequence !== markdownLinkSequence || activeDocument()?.id !== targetDocument.id) return;
      const targetContainer =
        effectiveViewMode() === "read" ? $("#reading-document") : $("#preview-document");
      applyPendingMarkdownLinkNavigation(targetContainer, targetDocument, {
        announceMissing: true,
      });
    } else {
      pendingMarkdownLinkNavigation = null;
    }
  } catch (error) {
    if (sequence !== markdownLinkSequence) return;
    pendingMarkdownLinkNavigation = null;
    const payload = errorPayload(error);
    const code = payload?.application_code || payload?.data?.application_code || payload?.code;
    toast(
      code === "MARDAS-LINK-NOT-FOUND"
        ? t("linkedMarkdownMissing")
        : t("linkedMarkdownUnavailable"),
      "warning",
    );
  } finally {
    delete link.dataset.opening;
  }
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
    const result = await previewDocumentText({
      path: model.path,
      content: model.content,
      options: previewOptions(),
    });
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
    const result = await validateDocumentText({
      path: model.path,
      content: model.content,
      options: previewOptions(),
    });
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
    if (sequence !== state.assetSequence || !contextIsCurrent(context, { requireContent: false }))
      return;
    await allowDocumentImages(model);
    if (sequence !== state.assetSequence || !contextIsCurrent(context, { requireContent: false }))
      return;
    renderAssets(Array.isArray(result.assets) ? result.assets : []);
  } catch (error) {
    if (sequence !== state.assetSequence || !contextIsCurrent(context, { requireContent: false }))
      return;
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
  const extension = String(
    asset.extension || asset.name?.slice(asset.name.lastIndexOf(".")) || "",
  ).toLowerCase();
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
  const model = activeDocument();
  let name = state.activeSidebar;
  if (!model && (documentOnly.includes(name) || name === "problems")) name = "project";
  else if (!isMarkdownModel(model) && documentOnly.includes(name))
    name = state.project ? "project" : "problems";
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
  if (name === "outline") {
    activateNavigator("outline");
    return;
  }
  if ($(`[data-sidebar="${name}"]`)?.disabled) return;
  if (!workspacePaneOpen("sidebar")) {
    setWorkspacePaneOpen("sidebar", true);
    applyWorkspaceLayout({ persist: !isCompactDrawer("sidebar") });
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
    const target = $("#reading-document")?.querySelector(
      `[data-source-line="${Number(line) || 1}"]`,
    );
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
    for (let index = 0; index < Math.max(0, line - 1); index += 1)
      offset += lines[index].length + 1;
    offset += Math.max(0, column - 1);
    editor.focus();
    editor.setSelectionRange(offset, offset);
  }
  updateEditorMetrics();
  syncPreviewToEditorLine(Number(line) || 1, { center: true });
}

function findSnapshot() {
  return {
    documentId: activeDocument()?.id,
    text: currentEditor().value,
    query: $("#find-query").value,
  };
}

function updateFindMatches(options = {}) {
  const { matches, index } = findSession.refresh(findSnapshot(), options);
  const query = $("#find-query").value;
  $("#find-count").textContent = matches.length
    ? `${index + 1}/${matches.length}`
    : query
      ? t("noFindResults")
      : t("findPrompt");
  $("#find-bar").dataset.noResults = String(Boolean(query) && !matches.length);
  $("#find-previous").disabled = $("#find-next").disabled = !matches.length;
  $("#replace-one").disabled = $("#replace-all").disabled = !matches.length || !documentEditable();
  editorAdapter?.setSearchMatches?.(matches, index);
  return matches;
}

function selectFindMatch(index, { direction = null } = {}) {
  const snapshot = findSnapshot();
  const match =
    direction === null
      ? findSession.select(snapshot, index)
      : findSession.move(snapshot, direction);
  if (!match) return;
  const editor = currentEditor();
  // Keep typing and Enter/Shift+Enter in the search field. Drawing a result
  // must not steal focus after the first matching character of the query.
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

function showFindReplacement(replace) {
  $("#find-replace-row").classList.toggle("hidden", !replace);
  $("#toggle-replace").setAttribute("aria-expanded", String(replace));
}

function openFind({ replace = false } = {}) {
  if (!activeDocument()) return;
  // Search selects the actual Markdown, and replacement requires an explicit
  // visible editing surface rather than changing a hidden reader buffer.
  if (effectiveViewMode() === "read") setViewMode("source");
  $("#find-bar").classList.remove("hidden");
  showFindReplacement(replace);
  const editor = currentEditor();
  const selected = editor.value.slice(editor.selectionStart, editor.selectionEnd);
  if (selected && !selected.includes("\n")) $("#find-query").value = selected;
  updateFindMatches({ reset: true });
  $("#find-query").focus();
  $("#find-query").select();
}

function closeFind({ restoreFocus = true } = {}) {
  $("#find-bar").classList.add("hidden");
  findSession.clear();
  editorAdapter?.setSearchMatches?.();
  if (restoreFocus) focusDocument();
}

function moveFind(direction) {
  selectFindMatch(null, { direction });
}

function replaceCurrentMatch() {
  if (!documentEditable()) return;
  const previousFocus = document.activeElement?.matches?.("#find-query,#replace-query")
    ? document.activeElement
    : null;
  const editor = currentEditor();
  const match = findSession.current(findSnapshot());
  if (!match) return;
  const replacement = $("#replace-query").value;
  applyEditorResult(replaceSelection(editor.value, match.start, match.end, replacement));
  updateFindMatches({ anchor: match.start + replacement.length });
  const { index } = findSession.refresh(findSnapshot());
  if (index >= 0) selectFindMatch(index);
  if (previousFocus)
    (previousFocus.disabled ? $("#replace-query") : previousFocus).focus({ preventScroll: true });
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
  applyEditorResult(
    replaceSelection(editor.value, editor.selectionStart, editor.selectionEnd, value),
  );
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
  if (command === "bold")
    result = wrapSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "**",
      "**",
      "bold text",
    );
  if (command === "italic")
    result = wrapSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "_",
      "_",
      "italic text",
    );
  if (command === "link")
    result = wrapSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "[",
      "](https://)",
      "link text",
    );
  if (command === "code")
    result = wrapSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "`",
      "`",
      "code",
    );
  if (command === "heading")
    result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "## ");
  if (command === "citation")
    result = replaceSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "[@citation-key]",
      2,
    );
  if (command === "strike")
    result = wrapSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "~~",
      "~~",
      "struck text",
    );
  if (command === "bullet-list")
    result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "- ");
  if (command === "ordered-list")
    result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "1. ");
  if (command === "task-list")
    result = prefixSelectedLines(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "- [ ] ",
    );
  if (command === "quote")
    result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "> ");
  if (command === "image")
    result = wrapSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "![",
      "](assets/image.png)",
      "alt text",
    );
  if (command === "rule")
    result = replaceSelection(editor.value, editor.selectionStart, editor.selectionEnd, "\n---\n");
  if (command === "code-block") {
    result = wrapSelection(
      editor.value,
      editor.selectionStart,
      editor.selectionEnd,
      "```\n",
      "\n```",
      "code",
    );
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
  const anchor = button.getClientRects().length ? button : $("#workspace-view-menu-button");
  positionToolbarPopover(menu, anchor);
  menu.querySelector("button:not(:disabled)")?.focus({ preventScroll: true });
}

function positionToolbarPopover(menu, anchor) {
  const box = anchor.getBoundingClientRect();
  menu.style.top = `${box.bottom + 4}px`;
  // Anchored to the button's leading edge, and kept inside the window: the
  // strip mirrors, so the same menu opens from the other side in Persian.
  const start = document.documentElement.dir === "rtl" ? window.innerWidth - box.right : box.left;
  const room = window.innerWidth - menu.offsetWidth - 8;
  menu.style.insetInlineStart = `${Math.max(8, Math.min(start, room))}px`;
}

function toggleWorkspaceLayoutMenu(force) {
  togglePopoverMenu("#workspace-layout-menu", "#workspace-layout-button", force);
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

function focusToolbarControl(selector) {
  const button = $(selector);
  (button?.getClientRects().length ? button : $("#workspace-view-menu-button"))?.focus({
    preventScroll: true,
  });
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
  const movable = [
    ...parts.bar.querySelectorAll("[data-format-movable]"),
    ...parts.menu.querySelectorAll("[data-format-movable]"),
  ];
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
  const candidates = focusableElements(document.body).filter(
    (element) => !surface.contains(element) && element.offsetParent !== null,
  );
  if (!candidates.length) return;
  const before = [];
  const after = [];
  for (const element of candidates) {
    const where = surface.compareDocumentPosition(element);
    if (where & Node.DOCUMENT_POSITION_PRECEDING) before.push(element);
    else if (where & Node.DOCUMENT_POSITION_FOLLOWING) after.push(element);
  }
  // Wrapping matches what the browser does at either end of the document.
  const target = backwards ? before.at(-1) || after.at(-1) : after[0] || before[0];
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
    const result =
      model.preview && model.previewContentVersion === model.contentVersion
        ? model.preview
        : await previewDocumentText({
            path: model.path,
            content: model.content,
            options: previewOptions(),
          });
    if (!contextIsCurrent(context)) {
      toast(t("copyDocumentChanged"));
      return;
    }
    const article = document.createElement("div");
    article.append(
      safePreviewHtml(
        `${result.body_html || ""}${result.reference_lists_html || ""}${result.bibliography_html || ""}`,
        "clipboard-",
      ),
    );
    await typesetPreviewMath(article, {
      isCurrent: () => contextIsCurrent(context),
      errorLabel: t("previewMathFailed"),
    });
    if (!contextIsCurrent(context)) return;
    if (await copyToClipboard(article.textContent || "", { html: article.innerHTML }))
      toast(t("copied"), "success");
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
    if (
      !contextIsCurrent(context) ||
      intent !== state.documentActivationSequence ||
      !documentEditable() ||
      editor.selectionStart !== start ||
      editor.selectionEnd !== end
    )
      return;
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
    {
      key: "copy",
      label: t("copy"),
      enabled: hasSelection,
      run: () => copyToClipboard(selectionOrDocument()),
    },
    {
      key: "copyHtml",
      label: t("copyAsHtml"),
      enabled: isMarkdownModel(model) && Boolean(model?.content.trim()),
      run: copyAsHtml,
    },
    {
      key: "copyPlain",
      label: t("copyAsPlainText"),
      enabled: true,
      run: () => copyToClipboard(selectionOrDocument()),
    },
    { key: "paste", label: t("pasteAsPlainText"), enabled: editable, run: pasteAsPlainText },
    { separator: true },
    { key: "image", label: t("insertImage"), enabled: editable, run: importAsset },
    {
      key: "citation",
      label: t("insertCitation"),
      enabled: editable,
      run: () => editorCommand("citation"),
    },
    { key: "table", label: t("insertTable"), enabled: editable, run: () => editorCommand("table") },
    { separator: true },
    {
      key: "validate",
      label: t("checkDocument"),
      enabled: isMarkdownModel(model),
      run: validateActiveDocument,
    },
    { key: "export", label: t("commandExport"), enabled: Boolean(model), run: openWorkspaceExport },
    {
      key: "reveal",
      label: t("showInFolder"),
      enabled: Boolean(model?.path),
      run: () => invoke("reveal_path", { path: model.path }).catch(() => {}),
    },
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
    const health = await invoke("sidecar_request", {
      request_id: requestId("health"),
      method: "system.health",
      params: {},
    });
    element.dataset.state = "ready";
    element.querySelector("span").dataset.i18n = "engineReady";
    element.querySelector("span").textContent = t("engineReady");
    $("#runtime-detail").textContent =
      `${health.engine_version || ""} · ${health.runtime?.platform || t("localRuntime")}`;
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
  const utilityWidth = matchMedia("(min-width: 1001px)");
  const updateUtilities = () => {
    $("#app-utilities").open = utilityWidth.matches;
  };
  updateUtilities();
  utilityWidth.addEventListener("change", updateUtilities);
  // Fixed popovers belong to the viewport. Keeping them inside a size-query
  // container would change their containing block and clip them over a pane.
  for (const menu of $$(".popover-menu, #editor-context-menu")) document.body.append(menu);
  const layoutMenu = $("#workspace-layout-menu");
  const layoutTrigger = $("#workspace-layout-button");
  layoutTrigger.addEventListener("click", () => toggleWorkspaceLayoutMenu());
  layoutMenu.addEventListener("keydown", (event) => {
    const items = [...layoutMenu.querySelectorAll("button:not(:disabled)")];
    const index = items.indexOf(document.activeElement);
    const leavesGroup =
      event.key === "Tab" && (event.shiftKey ? index === 0 : index === items.length - 1);
    if (event.key === "Escape" || leavesGroup) {
      event.preventDefault();
      toggleWorkspaceLayoutMenu(false);
      layoutTrigger.focus({ preventScroll: true });
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) || !items.length) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next].focus({ preventScroll: true });
  });
  document.addEventListener("focusin", (event) => {
    if (
      !layoutMenu.classList.contains("hidden") &&
      !layoutMenu.contains(event.target) &&
      event.target !== layoutTrigger
    ) {
      toggleWorkspaceLayoutMenu(false);
    }
  });
  $("#workspace-toggle-preview").addEventListener("click", () =>
    toggleSidePreview({ keepFocus: true }),
  );
  $("#workspace-reset-panel-sizes").addEventListener("click", resetWorkspacePaneSizes);
  $("#document-mode-help").addEventListener("click", () =>
    modalManager.open($("#view-guide-modal")),
  );
  $("#close-view-guide").addEventListener("click", () =>
    modalManager.close($("#view-guide-modal")),
  );
  $("#workflow-new").addEventListener("click", createUntitledDocument);
  $("#command-button").addEventListener("click", openCommandPalette);
  $("#help-button").addEventListener("click", openHelp);
  $("#settings-button").addEventListener("click", () => openSettings());
  for (const button of $$("button[data-view-mode]")) {
    button.addEventListener("click", () => setViewMode(button.dataset.viewMode));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const buttons = $$("button[data-view-mode]").filter((item) => !item.disabled);
      if (buttons.length < 2) return;
      const index = buttons.indexOf(button);
      const rtl = document.documentElement.dir === "rtl";
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? buttons.length - 1
            : (index + ((event.key === "ArrowRight") !== rtl ? 1 : -1) + buttons.length) %
              buttons.length;
      setViewMode(buttons[next].dataset.viewMode);
      buttons[next].focus();
    });
  }
  $("#reset-advanced").addEventListener("click", resetAdvancedOptions);
  $("#export-preset").addEventListener("change", (event) => selectPreset(event.target.value));
  $("#export-open-settings").addEventListener("click", () => setExportSettingsOpen(true));
  $("#export-close-settings").addEventListener("click", () => setExportSettingsOpen(false));
  for (const button of $$("[data-export-pane]")) {
    button.addEventListener("click", () => setExportPane(button.dataset.exportPane));
  }
  $("#preview-zoom-in").addEventListener("click", () => exportPreviewDeck()?.zoomBy(1));
  $("#preview-zoom-out").addEventListener("click", () => exportPreviewDeck()?.zoomBy(-1));
  $("#preview-fit-width").addEventListener("click", () =>
    exportPreviewDeck()?.setZoomMode("fit-width"),
  );
  $("#preview-fit-page").addEventListener("click", () =>
    exportPreviewDeck()?.setZoomMode("fit-page"),
  );
  $("#preview-guides").addEventListener("click", () => exportPreviewDeck()?.toggleGuides());
  $("#preview-prev-page").addEventListener("click", () => movePreviewPage(-1));
  $("#preview-next-page").addEventListener("click", () => movePreviewPage(1));
  $("#export-preview-retry").addEventListener("click", () => schedulePdfPreview(0));
  $("#workflow-quick").addEventListener("click", openFileExport);
  $("#workflow-open").addEventListener("click", chooseAuthoringFiles);
  $("#workflow-project").addEventListener("click", chooseProjectDirectory);
  $("#workflow-book").addEventListener("click", openNewBookModal);
  $("#export-back").addEventListener("click", () => {
    showView("workspace");
    if (activeDocument()) focusDocument();
    else $("#workspace-export").focus({ preventScroll: true });
  });
  $("#close-export-format").addEventListener("click", () =>
    modalManager.close($("#export-format-modal")),
  );
  $("#choose-source").addEventListener("click", chooseExportSource);
  $("#preview-choose-source").addEventListener("click", chooseExportSource);
  $("#choose-output").addEventListener("click", chooseExportOutput);
  $("#validate-button").addEventListener("click", validateExportDocument);
  $("#export-form").addEventListener("submit", exportDocument);
  $("#cancel-button").addEventListener("click", cancelExport);
  $("#export-show-details").addEventListener("click", () =>
    modalManager.open($("#export-details-modal"), {
      initialFocus: "#export-close-details",
    }),
  );
  $("#export-close-details").addEventListener("click", () =>
    modalManager.close($("#export-details-modal")),
  );
  $("#open-pdf").addEventListener("click", () => openResult(false));
  $("#reveal-pdf").addEventListener("click", () => openResult(true));
  $("#clear-recents").addEventListener("click", () => {
    state.recents = writeRecents([]);
    renderRecents();
  });

  $("#workspace-toggle-files")?.addEventListener("click", () =>
    toggleWorkspacePane("files", { keepFocus: true }),
  );
  $("#workspace-toggle-formatting")?.addEventListener("click", () =>
    toggleWorkspacePane("formatting"),
  );
  $("#writing-appearance-button")?.addEventListener("click", () => toggleWritingAppearance());
  $("#writing-appearance-close")?.addEventListener("click", () => {
    toggleWritingAppearance(false);
    focusToolbarControl("#writing-appearance-button");
  });
  $("#writing-font")?.addEventListener("change", (event) =>
    updateDocumentView({ writingFont: event.target.value }),
  );
  $("#writing-density")?.addEventListener("change", (event) =>
    updateDocumentView({ writingDensity: event.target.value }),
  );
  $("#writing-zoom")?.addEventListener("input", (event) =>
    updateDocumentView({ documentZoom: Number(event.target.value) }),
  );
  $("#writing-appearance-reset")?.addEventListener("click", () =>
    updateDocumentView({
      documentZoom: 100,
      writingDensity: "comfortable",
      writingFont: "document",
    }),
  );
  $("#writing-appearance")?.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    toggleWritingAppearance(false);
    focusToolbarControl("#writing-appearance-button");
  });
  const navigatorTabs = $$("[data-navigator-tab]");
  for (const button of navigatorTabs) {
    button.addEventListener("click", () => activateNavigator(button.dataset.navigatorTab));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const tabs = navigatorTabs.filter((tab) => !tab.disabled);
      const backwards =
        event.key === (document.documentElement.dir === "rtl" ? "ArrowRight" : "ArrowLeft");
      const index = tabs.indexOf(button);
      const next =
        event.key === "Home"
          ? tabs[0]
          : event.key === "End"
            ? tabs.at(-1)
            : tabs[(index + (backwards ? -1 : 1) + tabs.length) % tabs.length];
      if (next) {
        activateNavigator(next.dataset.navigatorTab);
        next.focus();
      }
    });
  }
  $("#outline-filter")?.addEventListener("input", (event) => {
    outlineNavigator?.setFilter(event.target.value);
    $("#outline-collapse-all").disabled = Boolean(event.target.value);
  });
  $("#outline-expand-all")?.addEventListener("click", () => outlineNavigator?.expandAll());
  $("#outline-collapse-all")?.addEventListener("click", () => outlineNavigator?.collapseAll());
  $("#outline-follow")?.addEventListener("change", (event) =>
    outlineNavigator?.setFollow(event.target.checked),
  );
  let lastTextWheel = 0;
  document.addEventListener(
    "wheel",
    (event) => {
      if (
        !(event.ctrlKey || event.metaKey) ||
        !event.deltaY ||
        !event.target.closest(
          ".editor-surface,.reading-document,.preview-document,#book-review-document",
        )
      )
        return;
      event.preventDefault();
      const now = Date.now();
      if (now - lastTextWheel < 80) return;
      lastTextWheel = now;
      changeDocumentZoom(event.deltaY < 0 ? 1 : -1);
    },
    { passive: false },
  );
  $("#document-zoom-out")?.addEventListener("click", () => changeDocumentZoom(-1));
  $("#document-zoom-in")?.addEventListener("click", () => changeDocumentZoom(1));
  $("#document-zoom-reset")?.addEventListener("click", () => changeDocumentZoom(0));
  $("#document-toggle-width")?.addEventListener("click", () =>
    updateDocumentView({
      writingWidth: state.preferences.writingWidth === "full" ? "readable" : "full",
    }),
  );
  $("#workspace-quick-open")?.addEventListener("click", () => navigationPicker.open("files"));
  $("#navigator-new")?.addEventListener("click", createUntitledDocument);
  $("#tab-new-document")?.addEventListener("click", createStartTab);
  $("#navigator-open")?.addEventListener("click", chooseAuthoringFiles);
  $("#navigator-open-project")?.addEventListener("click", chooseProjectDirectory);
  $("#navigator-close")?.addEventListener("click", () => toggleWorkspacePane("files"));
  $("#inspector-close")?.addEventListener("click", () => toggleWorkspacePane("sidebar"));
  $("#workspace-focus")?.addEventListener("click", () => {
    toggleWorkspaceLayoutMenu(false);
    updatePreference({ focusMode: !state.preferences.focusMode });
    focusDocument();
  });
  $("#exit-focus-mode")?.addEventListener("click", () => {
    updatePreference({ focusMode: false });
    focusDocument();
  });
  $("#file-resizer")?.addEventListener("pointerdown", (event) => beginPaneResize(event, "files"));
  $("#file-resizer")?.addEventListener("keydown", (event) =>
    resizePaneWithKeyboard(event, "files"),
  );
  $("#reading-document")?.addEventListener("scroll", (event) => {
    if (
      readingDocumentId &&
      state.preferences.viewMode === "read" &&
      event.currentTarget.getClientRects().length
    ) {
      readingScroll.set(readingDocumentId, event.currentTarget.scrollTop);
      outlineNavigator?.setActiveLine(readingSourceLine(), { scroll: true });
    }
  });
  $("#document-actions-menu")?.addEventListener("click", (event) => {
    if (event.target.closest("button")) event.currentTarget.open = false;
  });
  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest("#document-actions-menu"))
      $("#document-actions-menu")?.removeAttribute("open");
  });
  let compactWorkspace = compactSidePanes.matches;
  window.addEventListener("resize", () => {
    const next = compactSidePanes.matches;
    if (next !== compactWorkspace) state.compactDrawer = null;
    compactWorkspace = next;
    applyWorkspaceLayout();
    requestAnimationFrame(revealActiveTab);
    if (!layoutMenu.classList.contains("hidden")) positionToolbarPopover(layoutMenu, layoutTrigger);
  });
  $("#workspace-new").addEventListener("click", createUntitledDocument);
  $("#workspace-open").addEventListener("click", chooseAuthoringFiles);
  $("#workspace-save").addEventListener("click", () => saveActiveDocument());
  $("#workspace-save-as").addEventListener("click", () => saveActiveDocument({ saveAs: true }));
  $("#workspace-validate").addEventListener("click", validateActiveDocument);
  $("#workspace-export").addEventListener("click", openWorkspaceExport);
  $("#workspace-import-asset").addEventListener("click", importAsset);
  $("#workspace-toggle-sidebar").addEventListener("click", () =>
    toggleWorkspacePane("sidebar", { keepFocus: true }),
  );
  $("#sidebar-resizer").addEventListener("pointerdown", (event) =>
    beginPaneResize(event, "sidebar"),
  );
  $("#preview-resizer").addEventListener("pointerdown", (event) =>
    beginPaneResize(event, "preview"),
  );
  $("#sidebar-resizer").addEventListener("keydown", (event) =>
    resizePaneWithKeyboard(event, "sidebar"),
  );
  $("#preview-resizer").addEventListener("keydown", (event) =>
    resizePaneWithKeyboard(event, "preview"),
  );
  $("#import-asset").addEventListener("click", importAsset);
  $("#refresh-assets").addEventListener("click", refreshAssets);
  $("#sidebar-open-project").addEventListener("click", chooseProjectDirectory);
  $("#refresh-project").addEventListener("click", refreshActiveProject);
  $("#close-project").addEventListener("click", closeActiveProject);
  $("#close-book-project").addEventListener("click", closeActiveProject);
  $("#run-project-search").addEventListener("click", runProjectSearch);
  $("#sidebar-new-book").addEventListener("click", openNewBookModal);
  $("#book-add-chapter").addEventListener("click", () => openChapterModal("add"));
  $("#book-validate").addEventListener("click", validateActiveBook);
  $("#book-preview").addEventListener("click", previewActiveBook);
  $("#book-export").addEventListener("click", () => {
    const context = currentProjectContext();
    openExportFormat(
      () => {
        if (!projectContextIsCurrent(context)) {
          toast(t("bookProjectChanged"), "warning");
          return;
        }
        return exportActiveBook();
      },
      { book: true },
    );
  });
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
  for (const container of [
    $("#reading-document"),
    $("#preview-document"),
    $("#book-review-document"),
  ]) {
    container?.addEventListener("click", (event) => void activateMarkdownDocumentLink(event));
    container?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || !event.target?.closest?.("a[data-mardas-markdown-href]")) return;
      void activateMarkdownDocumentLink(event);
    });
  }
  for (const checkbox of $$("[data-content-auto]"))
    checkbox.addEventListener("change", () => {
      updatePreference({ autoPreview: checkbox.checked });
      if (checkbox.checked && contentViewVisible()) void refreshPreview();
      else schedulePreview();
    });
  $("#frontmatter-form").addEventListener("submit", applyFrontMatter);
  $("#find-query").addEventListener("input", () => {
    if (updateFindMatches({ reset: true }).length) selectFindMatch(0);
  });
  $("#find-query").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      moveFind(event.shiftKey ? -1 : 1);
    }
  });
  $("#toggle-replace").addEventListener("click", () => {
    showFindReplacement($("#toggle-replace").getAttribute("aria-expanded") !== "true");
    $("#find-query").focus();
  });
  $("#find-bar").addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeFind();
    }
    const shortcut = authoringShortcutKey(event);
    if (["f", "h"].includes(shortcut)) {
      event.preventDefault();
      event.stopPropagation();
      if (shortcut === "h") showFindReplacement(true);
      $("#find-query").focus();
      $("#find-query").select();
    }
  });
  $("#replace-query").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      replaceCurrentMatch();
      $("#replace-query").focus();
    }
  });
  $("#find-previous").addEventListener("click", () => moveFind(-1));
  $("#find-next").addEventListener("click", () => moveFind(1));
  $("#replace-one").addEventListener("click", replaceCurrentMatch);
  $("#replace-all").addEventListener("click", replaceAllMatches);
  $("#close-find").addEventListener("click", closeFind);
  $$("[data-editor-command]").forEach((button) =>
    button.addEventListener("click", () => {
      if (button.closest("#heading-menu")) toggleHeadingMenu(false);
      if (button.closest("#insert-menu")) toggleInsertMenu(false);
      editorCommand(button.dataset.editorCommand);
    }),
  );
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
      focusToolbarControl("#insert-menu-button");
      return;
    }
    if (!["ArrowUp", "ArrowDown"].includes(event.key) || index < 0) return;
    event.preventDefault();
    const next =
      event.key === "ArrowDown"
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
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
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
      focusToolbarControl("#heading-menu-button");
      return;
    }
    if (!["ArrowUp", "ArrowDown"].includes(event.key) || index < 0) return;
    event.preventDefault();
    const next =
      event.key === "ArrowDown"
        ? (index + 1) % items.length
        : (index - 1 + items.length) % items.length;
    items[next].focus();
  });
  document.addEventListener("pointerdown", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target?.closest("#workspace-layout-menu, #workspace-layout-button"))
      toggleWorkspaceLayoutMenu(false);
    if (!target?.closest("#heading-menu, #heading-menu-button")) toggleHeadingMenu(false);
    if (!target?.closest("#insert-menu, #insert-menu-button")) toggleInsertMenu(false);
    if (!target?.closest("#writing-appearance, #writing-appearance-button"))
      toggleWritingAppearance(false);
    if (!target?.closest("#format-overflow-menu, #format-overflow-button")) {
      toggleFormatOverflowMenu(false);
    }
    if (!target?.closest("#editor-context-menu")) closeEditorContextMenu();
  });
  const sidebarButtons = $$("[data-sidebar]");
  sidebarButtons.forEach((button) => {
    button.addEventListener("click", () => activateSidebar(button.dataset.sidebar));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      const index = sidebarButtons.indexOf(button);
      let targetIndex = index;
      const rtl = document.documentElement.dir === "rtl";
      if (event.key === "ArrowUp" || event.key === (rtl ? "ArrowRight" : "ArrowLeft"))
        targetIndex = (index - 1 + sidebarButtons.length) % sidebarButtons.length;
      if (event.key === "ArrowDown" || event.key === (rtl ? "ArrowLeft" : "ArrowRight"))
        targetIndex = (index + 1) % sidebarButtons.length;
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
  $("#cancel-settings").addEventListener("click", closeSettings);
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
  $$("[data-onboarding-action]").forEach((button) =>
    button.addEventListener("click", () => {
      state.onboardingIntent = normalizeOnboardingIntent(button.dataset.onboardingAction);
      setOnboardingStep(1);
    }),
  );
  $("#command-query").addEventListener("input", () => {
    resetCommandSelection();
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
      } else if (!modalManager.hasOpenModal() && compactSidePanes.matches && state.compactDrawer) {
        closeCompactDrawer();
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
    const formControl =
      event.target instanceof Element &&
      event.target.matches("input,textarea,select,[contenteditable='true']") &&
      !event.target.closest(".editor-surface");
    const tableEditorShortcut =
      event.target.closest?.(".cm-table-cell-editor") &&
      ["s", "f", "h", "p", "o", "n", "\\", "+", "=", "-", "0"].includes(key);
    if (formControl && !tableEditorShortcut) return;
    if (
      $("#workspace-view").classList.contains("active") &&
      !event.altKey &&
      ["+", "=", "-", "0"].includes(key)
    ) {
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
      ["b", "i", "k"].includes(key) &&
      $("#workspace-view").classList.contains("active") &&
      // Inside the editor these are the editor's own bindings. Handling them
      // here as well ran the command twice against a selection CodeMirror had
      // already changed.
      !(event.target instanceof Element && event.target.closest(".editor-surface"))
    ) {
      event.preventDefault();
      editorCommand(key === "b" ? "bold" : key === "i" ? "italic" : "link");
    }
  });

  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key !== "Escape" || event.defaultPrevented || modalManager.hasOpenModal()) return;
      const compactDrawer =
        event.target.closest?.(".editor-surface") &&
        compactSidePanes.matches &&
        state.compactDrawer;
      if (!state.preferences.focusMode && !compactDrawer) return;
      const completion = $(".cm-tooltip-autocomplete");
      const editorPopupFocused = event.target.closest?.(".cm-selection-toolbar");
      if (completion?.getClientRects().length || editorPopupFocused) return;
      if (
        [
          "#editor-context-menu",
          "#insert-menu",
          "#heading-menu",
          "#format-overflow-menu",
          "#workspace-view-menu",
          "#workspace-layout-menu",
        ].some((selector) => !$(selector)?.classList.contains("hidden"))
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      if (state.preferences.focusMode) updatePreference({ focusMode: false });
      else closeCompactDrawer();
      focusDocument();
    },
    true,
  );

  window.addEventListener("beforeunload", (event) => {
    // A visible table-cell draft belongs to this document too. Flush it before
    // serializing recovery rather than relying on a preceding blur event.
    if (editorAdapter?.commitPendingDrafts?.() === false) {
      event.preventDefault();
      event.returnValue = "";
    }
    for (const model of state.documents) if (documentDirty(model)) saveRecovery(model);
  });

  // Every way the format bar can change width — the window, a pane toggle, a
  // resize drag, the view mode, focus mode — arrives here as one signal.
  const formatBar = document.querySelector(".format-bar");
  createWorkspaceToolbar({
    toolbar: $(".document-toolbar"),
    menu: $("#workspace-view-menu"),
    trigger: $("#workspace-view-menu-button"),
    onLayout: syncFormatBarOverflow,
  });
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
  navigationPicker = createNavigationPicker({
    manager: modalManager,
    t,
    getEntries: (scope) =>
      scope === "headings"
        ? extractOutline(activeDocument()?.content || "").map((item) => ({
            id: `heading:${item.line}`,
            label: item.title,
            detail: `${t("lineShort")} ${item.line}`,
            line: item.line,
            level: item.level,
            documentId: activeDocument()?.id,
            contentVersion: activeDocument()?.contentVersion,
          }))
        : documentNavigationEntries(state.documents, state.project, state.recents),
    onChoose: async (entry, scope) => {
      if (scope === "headings") {
        if (
          entry.documentId === activeDocument()?.id &&
          entry.contentVersion === activeDocument()?.contentVersion
        )
          goToLine(entry.line);
        else focusDocument();
      } else {
        showView("workspace");
        if (entry.documentId) await activateDocument(entry.documentId);
        else if (entry.recentPath) await openAuthoringPaths([entry.recentPath]);
        else await openProjectRelativeFile(entry.relativePath);
      }
    },
  });
  applyInterfacePreferences();
  applyWorkspaceLayout();
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
    requestOnlineImage: (origin, source) => onlineImageOptions().onRequest(origin, source),
    renderMath: (container, { isCurrent } = {}) =>
      typesetPreviewMath(container, { isCurrent, errorLabel: t("previewMathFailed") }),
    getCompletions: () =>
      activeDocument()?.projectPath === state.project?.path ? state.bibliographyEntries : [],
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
    bindEditorHistoryShortcuts(editorAdapter);
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
      setExportProgress(percent);
      if (params.message && !state.cancelledExportRequestId) {
        updateExportMessage(params.message);
      }
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
          await clearProjectState();
        }
      }
      if (session.paths.length) {
        const restoration = openAuthoringPaths(session.paths);
        const activationSequence = state.documentActivationSequence;
        await restoration;
        const active = findDocumentByPath(state.documents, session.activePath);
        if (active && activationSequence === state.documentActivationSequence)
          await activateDocument(active.id);
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
}

boot();
