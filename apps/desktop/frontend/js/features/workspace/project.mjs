import { invoke } from "../../adapters/tauri.mjs";
import {
  openProject,
  refreshProject,
  startProjectSearch,
  cancelSidecarRequest,
} from "../../adapters/project-api.mjs";
import { pathKey } from "../../core/documents.mjs";

export function createProjectWorkspace({
  state,
  query: $,
  activeDocument,
  openProjectRelativeFile,
  invalidateBookTaskForProjectChange,
  applyProjectPayload,
  renderFileNavigator,
  showView,
  activateSidebar,
  closeCompactDrawer,
  setTruncatableText,
  t,
  toast,
  errorText,
  errorPayload,
}) {
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
    const previousProjectPath = state.project?.path || null;
    const activationSequence = ++state.documentActivationSequence;
    const handoff =
      pathKey(path) !== pathKey(state.project?.path)
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
    const switchedProject =
      pathKey(previousProjectPath) !== pathKey(payload.project?.path || payload.path);
    if (openFirstChapter && firstChapter && (!activeDocument() || switchedProject)) {
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
    $("#refresh-project").hidden = !project;
    $("#close-project").hidden = !project;
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
      const selected =
        current?.projectPath === project.path && current?.projectRelativePath === file.path;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-current", selected ? "page" : "false");
      if (["markdown", "text", "config", "toml", "bibliography", "json"].includes(file.kind)) {
        button.addEventListener("click", async () => {
          await openProjectRelativeFile(file.path);
          closeCompactDrawer("files");
        });
      } else {
        button.disabled = true;
        button.title = `${file.path}\n${t("unsupportedProjectFile")}`;
      }
      list.append(button);
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
      button.querySelector(".match-location").textContent =
        `${match.path}:${match.line}:${match.column}`;
      setTruncatableText(button.querySelector(".match-preview"), match.preview || "");
      button.addEventListener("click", () =>
        openProjectRelativeFile(match.path, { line: match.line, column: match.column }),
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

  return {
    chooseProjectDirectory,
    loadProject,
    refreshActiveProject,
    renderProjectWorkspace,
    cancelActiveProjectSearch,
    runProjectSearch,
  };
}
