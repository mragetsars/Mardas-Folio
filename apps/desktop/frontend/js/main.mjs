import { basename, buildDocumentParams, defaultOutputPath, validateExportSelection } from "./core/export-request.mjs";
import { createTranslator, supportedLocale } from "./core/i18n.mjs";
import { PRESETS, presetById } from "./core/presets.mjs";
import { addRecent, readRecents, writeRecents } from "./core/recents.mjs";
import { invoke, listen } from "./core/tauri.mjs";
import {
  createDocument,
  closeDocument,
  documentDirty,
  findDocumentByPath,
  markDocumentSaved,
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
  bibliographyIndex,
  cancelSidecarRequest,
  openProject,
  readProjectFile,
  refreshProject,
  startProjectSearch,
} from "./core/project-api.mjs";
import {
  importDocumentAsset,
  listDocumentAssets,
  previewDocumentText,
  readDocument,
  saveDocument,
  validateDocumentText,
} from "./core/authoring-api.mjs";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {
  locale: supportedLocale(localStorage.getItem("mardas.desktop.locale") || navigator.language),
  presetId: "general",
  sourcePath: "",
  outputPath: "",
  activeRequestId: null,
  outputResult: null,
  recents: readRecents(),
  documents: [],
  activeDocumentId: null,
  previewTimer: null,
  recoveryTimer: null,
  previewSequence: 0,
  pendingRecovery: null,
  recoveryQueue: [],
  findMatches: [],
  findIndex: -1,
  activeSidebar: "outline",
  project: null,
  projectSearchSequence: 0,
  activeProjectSearchRequestId: null,
  bibliographySequence: 0,
  bibliographyEntries: [],
  previewSyncing: false,
};
let editorAdapter = null;
const translator = createTranslator(state.locale);
const t = (key) => translator.t(key);

function requestId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function activeDocument() {
  return state.documents.find((document) => document.id === state.activeDocumentId) ?? null;
}

function setLocale(value) {
  state.locale = supportedLocale(value);
  translator.locale = state.locale;
  localStorage.setItem("mardas.desktop.locale", state.locale);
  document.documentElement.lang = state.locale;
  document.documentElement.dir = state.locale === "fa" ? "rtl" : "ltr";
  $("#locale-button").textContent = state.locale === "fa" ? "EN" : "فا";
  $$('[data-i18n]').forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  $$('[data-i18n-placeholder]').forEach((element) => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });
  renderPresets();
  renderRecents();
  renderWorkspace();
  renderSummary();
}

function showView(name) {
  $$(".view").forEach((element) => element.classList.remove("active"));
  $(`#${name}-view`)?.classList.add("active");
  $("#app-main")?.focus({ preventScroll: true });
}

function toast(message, kind = "info") {
  const element = document.createElement("div");
  element.className = `toast ${kind}`;
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

function exportOverrides() {
  return {
    document_language: $("#document-language").value,
    page_size: $("#page-size").value,
    style: $("#appearance-style").value,
    toc: $("#include-toc").checked,
  };
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
    button.innerHTML = `<i></i><strong></strong><small></small>`;
    button.querySelector("strong").textContent = t(preset.titleKey);
    button.querySelector("small").textContent = t(preset.descriptionKey);
    button.addEventListener("click", () => selectPreset(preset.id));
    grid.append(button);
  }
}

function selectPreset(id) {
  const preset = presetById(id);
  state.presetId = preset.id;
  $("#document-language").value = preset.options.document_language || "auto";
  $("#page-size").value = preset.options.page_size || "A4";
  $("#appearance-style").value = preset.options.style || "modern";
  $("#include-toc").checked = Boolean(preset.options.toc);
  renderPresets();
  renderSummary();
}

function renderSummary() {
  const container = $("#preset-summary");
  if (!container) return;
  const preset = presetById(state.presetId);
  const options = { ...preset.options, ...exportOverrides() };
  const rows = [
    [t("preset"), t(preset.titleKey)],
    [t("quality"), options.quality_profile === "strict-publication" ? t("strict") : t("standard")],
    [t("page"), options.page_size],
    [t("toc"), options.toc ? t("enabled") : t("disabled")],
  ];
  container.replaceChildren(...rows.map(([label, value]) => {
    const row = document.createElement("div");
    row.innerHTML = `<span></span><strong></strong>`;
    row.querySelector("span").textContent = label;
    row.querySelector("strong").textContent = value;
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
    button.innerHTML = `<span>MD</span><div><strong></strong><small></small></div><b>←</b>`;
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

function openExportSource(path) {
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
  working(true);
  $("#success-actions").classList.add("hidden");
  const id = requestId("render");
  state.activeRequestId = id;
  try {
    const params = buildDocumentParams({ sourcePath: state.sourcePath, outputPath: state.outputPath, presetId: state.presetId, overrides: exportOverrides() });
    const result = await invoke("sidecar_request", { request_id: id, method: "render.document", params });
    state.outputResult = result;
    $("#progress-bar").style.width = "100%";
    $("#progress-label").textContent = "100%";
    setExportStatus("success", "successTitle", `${t("successMessage")} ${result.output_path || state.outputPath}`);
    $("#success-actions").classList.remove("hidden");
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
  tab.tabIndex = 0;
  tab.className = `document-tab${model.id === state.activeDocumentId ? " active" : ""}${documentDirty(model) ? " dirty" : ""}`;
  tab.dataset.documentId = model.id;
  tab.setAttribute("role", "tab");
  tab.setAttribute("aria-selected", String(model.id === state.activeDocumentId));
  tab.innerHTML = `<i class="dirty-dot"></i><span class="tab-name"></span><button class="tab-close" type="button" aria-label="${t("close")}">×</button>`;
  tab.querySelector(".tab-name").textContent = model.title;
  tab.addEventListener("click", (event) => {
    if (event.target.closest(".tab-close")) return;
    activateDocument(model.id);
  });
  tab.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activateDocument(model.id);
    }
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
  const editor = $("#markdown-editor");
  const lines = Math.max(1, editor.value.split("\n").length);
  $("#line-gutter").textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
  $("#line-gutter").scrollTop = editor.scrollTop;
}

function updateEditorMetrics() {
  const editor = $("#markdown-editor");
  const metrics = textMetrics(editor.value, editor.selectionStart);
  $("#cursor-status").textContent = `Ln ${metrics.line}, Col ${metrics.column}`;
  $("#word-status").textContent = `${metrics.words} words · ${metrics.characters} chars`;
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
  if (state.project) {
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
  ];
  $("#problem-count").textContent = String(diagnostics.length);
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
    if (diagnostic.line) button.addEventListener("click", () => goToLine(diagnostic.line, diagnostic.column || 1));
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

function renderWorkspace() {
  const model = activeDocument();
  renderDocumentTabs();
  const editor = editorAdapter || $("#markdown-editor");
  renderProjectWorkspace();
  if (!model) {
    editor.value = "";
    editor.disabled = true;
    $("#editor-title").textContent = t("untitled");
    $("#editor-path").textContent = "";
    renderOutline(null);
    renderCitations(null);
    renderProblems(null);
    return;
  }
  editor.disabled = false;
  if (editor.value !== model.content) editor.value = model.content;
  $("#editor-title").textContent = model.title;
  $("#editor-path").textContent = model.path || t("untitled");
  setSaveState(documentDirty(model) ? "dirty" : "saved");
  updateLineGutter();
  updateEditorMetrics();
  renderOutline(model);
  loadFrontMatterForm(model);
  renderCitations(model);
  renderProblems(model);
  renderPreview(model);
}

function activateDocument(id) {
  const model = state.documents.find((document) => document.id === id);
  if (!model) return;
  state.activeDocumentId = id;
  persistSession();
  renderWorkspace();
  (editorAdapter || $("#markdown-editor")).focus();
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
  (editorAdapter || $("#markdown-editor")).focus();
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
      const result = await readDocument(path);
      const model = createDocument({ path: result.path, content: result.content, revision: result.revision, readOnly: result.read_only });
      state.documents.push(model);
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
  const payload = await openProject(path);
  state.project = payload;
  state.bibliographyEntries = [];
  persistSession();
  renderProjectWorkspace();
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
    state.project = await refreshProject(state.project.path);
    renderProjectWorkspace();
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
  if (!state.project?.path) return;
  try {
    const result = await readProjectFile(state.project.path, relativePath);
    const existing = findDocumentByPath(state.documents, result.absolute_path);
    let model = existing;
    if (!model) {
      model = createDocument({
        path: result.absolute_path,
        content: result.content,
        revision: result.revision,
        readOnly: result.read_only,
      });
      model.projectPath = state.project.path;
      model.projectRelativePath = result.path;
      model.projectSha256 = result.sha256;
      state.documents.push(model);
    }
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
}

async function runProjectSearch() {
  const project = state.project;
  const query = $("#project-search-query").value.trim();
  if (!project?.path || !query) {
    renderProjectSearchResults({ matches: [] });
    return;
  }

  if (state.activeProjectSearchRequestId) {
    try {
      await cancelSidecarRequest(state.activeProjectSearchRequestId);
    } catch {
      // A completed request no longer needs cancellation.
    }
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
  $("#run-project-search").disabled = true;
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
      $("#run-project-search").disabled = false;
    }
  }
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
    const cited = Boolean(entry.cited || usedKeys.includes(key));
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
  if (!state.project?.path) {
    renderCitations(model);
    return;
  }
  const sequence = ++state.bibliographySequence;
  try {
    const result = await bibliographyIndex({
      projectPath: state.project.path,
      query: $("#citation-search").value.trim(),
      citedKeys: used,
      maxResults: 500,
    });
    if (sequence !== state.bibliographySequence) return;
    renderBibliographyEntries(result.entries, used);
    if (model) {
      model.bibliographyDiagnostics = Array.isArray(result.diagnostics)
        ? result.diagnostics
        : [];
      renderProblems(model);
    }
  } catch (error) {
    if (sequence !== state.bibliographySequence) return;
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
  $("#recovery-modal").classList.remove("hidden");
}

function resolveRecovery(restore) {
  const pending = state.pendingRecovery;
  if (!pending) return;
  if (restore) updateDocumentContent(pending.model, pending.recovery.content);
  else removeRecovery(pending.recovery.key);
  state.pendingRecovery = null;
  $("#recovery-modal").classList.add("hidden");
  activateDocument(pending.model.id);
  const next = state.recoveryQueue.shift();
  if (next) showRecovery(next.model, next.recovery);
}

async function saveActiveDocument({ saveAs = false, force = false } = {}) {
  const model = activeDocument();
  if (!model) return false;
  let path = model.path;
  if (!path || saveAs) {
    try {
      path = await invoke("pick_markdown_output", { suggested_path: model.path || `${model.title.replace(/\s+/g, "-")}.md` });
    } catch (error) {
      toast(errorText(error), "error");
      return false;
    }
    if (!path) return false;
  }
  setSaveState("saving");
  try {
    const previousRecoveryKey = recoveryKey(model);
    const result = await saveDocument({
      path,
      content: model.content,
      expectedRevision: path === model.path ? model.revision : null,
      force,
    });
    markDocumentSaved(model, result);
    removeRecovery(previousRecoveryKey);
    removeRecovery(model);
    saveRecent(model.path);
    persistSession();
    renderWorkspace();
    toast(t("documentSaved"), "success");
    return true;
  } catch (error) {
    const payload = errorPayload(error);
    if (payload?.code === "MARDAS-DOCUMENT-CONFLICT" || payload?.application_code === "MARDAS-DOCUMENT-CONFLICT") {
      setSaveState("dirty");
      const overwrite = globalThis.confirm(`${t("documentConflict")}\n\n${t("forceSave")}?`);
      if (overwrite) return saveActiveDocument({ saveAs: false, force: true });
      return false;
    }
    setSaveState("dirty");
    toast(errorText(error), "error");
    return false;
  }
}

function requestCloseDocument(id) {
  const model = state.documents.find((document) => document.id === id);
  if (!model) return;
  if (documentDirty(model) && !globalThis.confirm(`${model.title}: ${t("unsaved")}. ${t("close")}?`)) return;
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
  updateDocumentContent(model, (editorAdapter || $("#markdown-editor")).value);
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

function scheduleRecovery() {
  clearTimeout(state.recoveryTimer);
  state.recoveryTimer = setTimeout(() => {
    const model = activeDocument();
    if (!model || !documentDirty(model)) return;
    const result = saveRecovery(model);
    $("#recovery-status").textContent = result.ok ? t("recoverySaved") : result.reason === "too_large" ? t("recoveryTooLarge") : "";
    setTimeout(() => { if ($("#recovery-status")) $("#recovery-status").textContent = ""; }, 2500);
  }, 700);
}

function schedulePreview(delay = 650) {
  if (!$("#auto-preview")?.checked) return;
  clearTimeout(state.previewTimer);
  state.previewTimer = setTimeout(refreshPreview, delay);
}

function previewOptions() {
  const model = activeDocument();
  const metadata = parseFrontMatter(model?.content || "").fields;
  return {
    toc: Boolean(metadata.toc),
    document_language: metadata.lang || "auto",
    style: metadata.style || "modern",
    mode: metadata.mode || "light",
  };
}

function safePreviewHtml(value) {
  const template = document.createElement("template");
  template.innerHTML = String(value || "");
  template.content.querySelectorAll("script,iframe,object,embed,meta,base,link").forEach((element) => element.remove());
  template.content.querySelectorAll("*").forEach((element) => {
    for (const attribute of [...element.attributes]) {
      if (attribute.name.toLowerCase().startsWith("on")) element.removeAttribute(attribute.name);
      if (["href", "src"].includes(attribute.name.toLowerCase()) && /^\s*javascript:/i.test(attribute.value)) element.removeAttribute(attribute.name);
    }
  });
  return template.content;
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
  const target = container.querySelector(`#${CSS.escape(active.id)}`)
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
  const container = $("#preview-document");
  if (!model?.preview) {
    container.innerHTML = `<div class="empty-preview"><strong>${t("previewEmpty")}</strong></div>`;
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
    const sourceLine = Number(heading.dataset.sourceLine) || byId.get(heading.id)?.line || 0;
    if (!sourceLine) return;
    heading.dataset.sourceLine = String(sourceLine);
    heading.classList.add("preview-source-link");
    heading.title = `Line ${sourceLine}`;
    heading.addEventListener("click", () => goToLine(sourceLine));
  });
  const cursor = (editorAdapter || $("#markdown-editor"));
  const position = editorAdapter?.lineAtOffset(cursor.selectionStart)
    || textMetrics(cursor.value, cursor.selectionStart);
  syncPreviewToEditorLine(position.line);
}

async function refreshPreview() {
  const model = activeDocument();
  if (!model || !model.content.trim()) {
    renderPreview(model);
    return;
  }
  const sequence = ++state.previewSequence;
  $("#preview-loading").classList.remove("hidden");
  try {
    const result = await previewDocumentText({ path: model.path, content: model.content, options: previewOptions() });
    if (sequence !== state.previewSequence || activeDocument()?.id !== model.id) return;
    model.preview = result;
    model.diagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
    renderPreview(model);
    renderCitations(model);
    renderProblems(model);
    $("#preview-detail").textContent = result.title || t("previewHelp");
  } catch (error) {
    if (sequence !== state.previewSequence) return;
    const payload = errorPayload(error);
    model.diagnostics = payload?.details?.diagnostics || payload?.diagnostics || [];
    renderProblems(model);
    $("#preview-document").innerHTML = `<div class="empty-preview"><strong>${t("previewFailed")}</strong><small>${errorText(error)}</small></div>`;
  } finally {
    if (sequence === state.previewSequence) $("#preview-loading").classList.add("hidden");
  }
}

async function validateActiveDocument() {
  const model = activeDocument();
  if (!model) return;
  try {
    const result = await validateDocumentText({ path: model.path, content: model.content, options: previewOptions() });
    model.diagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
    renderProblems(model);
    activateSidebar("problems");
    toast(result.ok ? t("validMessage") : t("invalidMessage"), result.ok ? "success" : "error");
  } catch (error) {
    toast(errorText(error), "error");
  }
}

async function refreshAssets() {
  const model = activeDocument();
  if (!model?.path) {
    renderAssets([]);
    return;
  }
  try {
    const result = await listDocumentAssets(model.path);
    renderAssets(Array.isArray(result.assets) ? result.assets : []);
  } catch (error) {
    renderAssets([]);
    toast(errorText(error), "error");
  }
}

async function importAsset() {
  const model = activeDocument();
  if (!model?.path) {
    toast(t("saveBeforeAsset"), "error");
    return;
  }
  try {
    const source = await invoke("pick_document_asset");
    if (!source) return;
    const asset = await importDocumentAsset(model.path, source);
    toast(t("assetImported"), "success");
    insertAssetReference(asset);
    await refreshAssets();
  } catch (error) {
    toast(errorText(error), "error");
  }
}

function insertAssetReference(asset) {
  const extension = String(asset.extension || asset.name?.slice(asset.name.lastIndexOf(".")) || "").toLowerCase();
  const path = asset.relative_path || asset.name;
  if ([".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif", ".bmp"].includes(extension)) {
    insertAtCursor(`![${asset.name || "Image"}](${path})`);
  } else if (extension === ".bib") {
    const model = activeDocument();
    let content = upsertFrontMatter(model.content, "bibliography", [path]);
    content = upsertFrontMatter(content, "citations", true);
    applyEditorContent(content);
  }
}

function activateSidebar(name) {
  state.activeSidebar = name;
  $$("[data-sidebar]").forEach((button) => button.classList.toggle("active", button.dataset.sidebar === name));
  $$("[data-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
  if (name === "assets") refreshAssets();
  if (name === "project") renderProjectWorkspace();
  if (name === "citations") refreshBibliography();
}

function goToLine(line, column = 1) {
  const editor = editorAdapter || $("#markdown-editor");
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
  const editor = $("#markdown-editor");
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
  const editor = $("#markdown-editor");
  editor.focus();
  editor.setSelectionRange(match.start, match.end);
  const before = editor.value.slice(0, match.start);
  const line = before.split("\n").length;
  const lineHeight = Number.parseFloat(getComputedStyle(editor).lineHeight) || 24;
  editor.scrollTop = Math.max(0, (line - 4) * lineHeight);
  $("#find-count").textContent = `${state.findIndex + 1}/${matches.length}`;
  updateEditorMetrics();
}

function openFind({ replace = false } = {}) {
  $("#find-bar").classList.remove("hidden");
  $("#replace-query").classList.toggle("hidden", !replace);
  $("#replace-one").classList.toggle("hidden", !replace);
  $("#replace-all").classList.toggle("hidden", !replace);
  const editor = $("#markdown-editor");
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
  $("#markdown-editor").focus();
}

function moveFind(direction) {
  if (!state.findMatches.length) updateFindMatches();
  if (state.findMatches.length) selectFindMatch(state.findIndex + direction);
}

function replaceCurrentMatch() {
  const editor = $("#markdown-editor");
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
  const editor = $("#markdown-editor");
  editor.value = replaceAllLiteral(editor.value, query, replacement).text;
  editor.setSelectionRange(0, 0);
  onEditorInput();
  updateFindMatches();
}

function applyEditorResult(result) {
  const editor = $("#markdown-editor");
  editor.value = result.text;
  editor.focus();
  editor.setSelectionRange(result.start, result.end);
  onEditorInput();
}

function applyEditorContent(content) {
  const editor = $("#markdown-editor");
  const cursor = Math.min(editor.selectionStart, content.length);
  editor.value = content;
  editor.setSelectionRange(cursor, cursor);
  onEditorInput();
}

function insertAtCursor(value) {
  const editor = $("#markdown-editor");
  applyEditorResult(replaceSelection(editor.value, editor.selectionStart, editor.selectionEnd, value));
}

function editorCommand(command) {
  const editor = $("#markdown-editor");
  let result;
  if (command === "bold") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "**", "**", "bold text");
  if (command === "italic") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "_", "_", "italic text");
  if (command === "link") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "[", "](https://)", "link text");
  if (command === "code") result = wrapSelection(editor.value, editor.selectionStart, editor.selectionEnd, "`", "`", "code");
  if (command === "heading") result = prefixSelectedLines(editor.value, editor.selectionStart, editor.selectionEnd, "## ");
  if (command === "citation") result = replaceSelection(editor.value, editor.selectionStart, editor.selectionEnd, "[@citation-key]", 2);
  if (result) applyEditorResult(result);
}

function applyFrontMatter(event) {
  event.preventDefault();
  const model = activeDocument();
  if (!model) return;
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
  if (!model) return;
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
    $("#runtime-detail").textContent = `${health.engine_version || ""} · ${health.runtime?.platform || "local"}`;
  } catch (error) {
    element.dataset.state = "error";
    element.querySelector("span").dataset.i18n = "engineUnavailable";
    element.querySelector("span").textContent = t("engineUnavailable");
    $("#runtime-detail").textContent = "sidecar unavailable";
    toast(errorText(error), "error");
  }
}

function bindEvents() {
  $("#home-button").addEventListener("click", () => showView("start"));
  $("#locale-button").addEventListener("click", () => setLocale(state.locale === "fa" ? "en" : "fa"));
  $("#start-quick-export").addEventListener("click", () => showView("export"));
  $("#workflow-quick").addEventListener("click", () => showView("export"));
  $("#start-open-file").addEventListener("click", chooseAuthoringFiles);
  $("#workflow-open").addEventListener("click", chooseAuthoringFiles);
  $("#start-open-project").addEventListener("click", chooseProjectDirectory);
  $("#workflow-project").addEventListener("click", chooseProjectDirectory);
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
  for (const id of ["document-language", "page-size", "appearance-style", "include-toc"]) {
    $(`#${id}`).addEventListener("change", renderSummary);
  }

  $("#workspace-home").addEventListener("click", () => showView("start"));
  $("#workspace-new").addEventListener("click", createUntitledDocument);
  $("#workspace-open").addEventListener("click", chooseAuthoringFiles);
  $("#workspace-save").addEventListener("click", () => saveActiveDocument());
  $("#workspace-save-as").addEventListener("click", () => saveActiveDocument({ saveAs: true }));
  $("#workspace-validate").addEventListener("click", validateActiveDocument);
  $("#workspace-export").addEventListener("click", exportActiveDocument);
  $("#workspace-import-asset").addEventListener("click", importAsset);
  $("#import-asset").addEventListener("click", importAsset);
  $("#refresh-assets").addEventListener("click", refreshAssets);
  $("#sidebar-open-project").addEventListener("click", chooseProjectDirectory);
  $("#refresh-project").addEventListener("click", refreshActiveProject);
  $("#run-project-search").addEventListener("click", runProjectSearch);
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
  $("#auto-preview").addEventListener("change", () => { if ($("#auto-preview").checked) refreshPreview(); });
  $("#frontmatter-form").addEventListener("submit", applyFrontMatter);
  $("#find-query").addEventListener("input", () => { updateFindMatches(); if (state.findMatches.length) selectFindMatch(0); });
  $("#find-query").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); moveFind(event.shiftKey ? -1 : 1); } if (event.key === "Escape") closeFind(); });
  $("#find-previous").addEventListener("click", () => moveFind(-1));
  $("#find-next").addEventListener("click", () => moveFind(1));
  $("#replace-one").addEventListener("click", replaceCurrentMatch);
  $("#replace-all").addEventListener("click", replaceAllMatches);
  $("#close-find").addEventListener("click", closeFind);
  $$('[data-editor-command]').forEach((button) => button.addEventListener("click", () => editorCommand(button.dataset.editorCommand)));
  $$('[data-sidebar]').forEach((button) => button.addEventListener("click", () => activateSidebar(button.dataset.sidebar)));
  $("#restore-recovery").addEventListener("click", () => resolveRecovery(true));
  $("#discard-recovery").addEventListener("click", () => resolveRecovery(false));

  document.addEventListener("keydown", (event) => {
    const modifier = event.ctrlKey || event.metaKey;
    if (!modifier) return;
    const key = event.key.toLowerCase();
    if (key === "f") {
      event.preventDefault();
      openFind({ replace: false });
    } else if (key === "h") {
      event.preventDefault();
      openFind({ replace: true });
    } else if (key === "s") {
      event.preventDefault();
      saveActiveDocument({ saveAs: event.shiftKey });
    } else if (key === "o") {
      event.preventDefault();
      chooseAuthoringFiles();
    } else if (key === "n") {
      event.preventDefault();
      createUntitledDocument();
    } else if (["b", "i", "k"].includes(key) && $("#workspace-view").classList.contains("active")) {
      event.preventDefault();
      editorCommand(key === "b" ? "bold" : key === "i" ? "italic" : "link");
    }
  });

  window.addEventListener("beforeunload", () => {
    for (const model of state.documents) if (documentDirty(model)) saveRecovery(model);
  });
}

async function boot() {
  editorAdapter = createEditorAdapter($("#markdown-editor"), {
    onChange: onEditorInput,
    onSelectionChange: () => {
      updateEditorMetrics();
      const position = editorAdapter.lineAtOffset();
      syncPreviewToEditorLine(position.line);
    },
    onScroll: (scrollTop) => {
      $("#line-gutter").scrollTop = scrollTop;
      syncPreviewFromEditorScroll(scrollTop);
    },
  });
  setLocale(state.locale);
  selectPreset("general");
  bindEvents();
  renderAssets([]);
  renderProblems(null);
  renderCitations(null);
  try {
    await listen("sidecar-progress", (event) => {
      const params = event.payload?.params || {};
      if (params.request_id !== state.activeRequestId) return;
      const percent = Math.round(Math.max(0, Math.min(1, Number(params.fraction) || 0)) * 100);
      $("#progress-bar").style.width = `${percent}%`;
      $("#progress-label").textContent = `${percent}%`;
      if (params.message) $("#status-message").textContent = params.message;
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
          state.project = null;
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
  if (!state.documents.length) {
    const drafts = readRecoveries().filter((item) => !item.path);
    for (const recovery of drafts) {
      const model = createDocument({ content: recovery.content });
      if (recovery.key.startsWith("draft:")) model.id = recovery.key.slice("draft:".length);
      model.title = recovery.title || model.title;
      state.documents.push(model);
      state.activeDocumentId = model.id;
    }
    if (drafts.length) {
      showView("workspace");
      renderWorkspace();
      schedulePreview(120);
    }
  }
}

boot();
