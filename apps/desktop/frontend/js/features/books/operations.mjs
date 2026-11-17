import { invoke } from "../../adapters/tauri.mjs";
import { cancelSidecarRequest, refreshProject } from "../../adapters/project-api.mjs";
import {
  startBookExport,
  startBookPreview,
  startBookValidation,
} from "../../adapters/book-api.mjs";
import { documentDirty, pathKey } from "../../core/documents.mjs";
import { basename } from "../../core/path-names.mjs";
import { prepareBookFiles } from "../../core/book-preparation.mjs";
import { bookTaskBlocked, claimBookTask } from "../../core/book-task-state.mjs";
import { beginCancellationHandoff } from "../../core/task-handoff.mjs";
import { typesetPreviewMath } from "../../preview/math.mjs";

export function createBookOperations({
  state,
  query: $,
  queryAll: $$,
  getModalManager,
  bookProject,
  currentProjectContext,
  projectContextIsCurrent,
  applyProjectPayload,
  askConfirmation,
  saveDocument,
  refreshAuthoring,
  renderProblems,
  activateSidebar,
  safePreviewHtml,
  requestId,
  setTruncatableText,
  t,
  toast,
  errorText,
  errorPayload,
}) {
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
    refreshAuthoring();
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

  async function runBookTask(
    startTask,
    { successMessage = "", onSuccess = null, showProblems = false, beforePrepare = null } = {},
  ) {
    const projectPath = state.project?.path;
    const projectIdentity = pathKey(projectPath);
    let projectContext = currentProjectContext();
    // Claim before any picker, confirmation or save can yield to another click.
    const task = claimBookTask(state, () => ({
      requestId: null,
      promise: Promise.resolve().then(async () => {
        const isCurrent = () =>
          sequence === state.bookRequestSequence &&
          pathKey(state.project?.path) === projectIdentity;
        if (!projectIdentity || !isCurrent()) return null;
        if (beforePrepare && !(await beforePrepare())) return null;
        const prepared = await prepareBookFiles({
          projectPath,
          getDocuments: () => state.documents,
          isDirty: documentDirty,
          isCurrent,
          confirm: () =>
            askConfirmation({
              title: t("bookSaveChangesTitle"),
              message: t("bookSaveChangesHelp"),
              confirmLabel: t("bookSaveAndContinue"),
            }),
          save: saveDocument,
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
        refreshAuthoring();
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
    refreshAuthoring();
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
      if (
        result?.project?.path &&
        pathKey(result.project.path) !== projectContext.projectIdentity
      ) {
        return null;
      }
      if (result?.project) applyProjectPayload(result.project);
      if (showProblems) {
        state.projectDiagnostics = Array.isArray(result.diagnostics) ? result.diagnostics : [];
        renderProblems();
        activateSidebar("problems");
        const hasWarnings = state.projectDiagnostics.some((item) => item.severity === "warning");
        const message =
          result.ok === false
            ? t("bookInvalid")
            : hasWarnings
              ? t("bookValidWithWarnings")
              : t("bookValid");
        const kind = result.ok === false ? "error" : hasWarnings ? "warning" : "success";
        setBookOperationStatus(message, { kind });
        toast(message, kind);
        return result;
      }
      if (typeof onSuccess === "function") await onSuccess(result);
      setBookOperationStatus(successMessage || t("bookValid"), { kind: "success" });
      if (successMessage) toast(successMessage, "success");
      return result;
    } catch (error) {
      if (sequence !== state.bookRequestSequence || !projectContextIsCurrent(projectContext)) {
        return null;
      }
      const payload = errorPayload(error);
      const applicationCode =
        payload?.application_code || payload?.data?.application_code || payload?.code;
      if (applicationCode === "MARDAS-JOB-CANCELLED") {
        setBookOperationStatus(t("searchCancelled"), { kind: "warning" });
        return null;
      }
      const diagnostics =
        payload?.details?.diagnostics ||
        payload?.data?.details?.diagnostics ||
        payload?.diagnostics ||
        [];
      if (diagnostics.length) {
        state.projectDiagnostics = diagnostics;
        renderProblems();
        activateSidebar("problems");
      }
      setBookOperationStatus(errorText(error), { kind: "error" });
      toast(errorText(error), "error");
      return null;
    } finally {
      if (sequence === state.bookRequestSequence) {
        state.bookPreparing = false;
        refreshAuthoring();
        state.activeBookRequestId = null;
        state.activeBookCompletion = null;
        $("#book-cancel-operation")?.classList.add("hidden");
      }
      syncBookOperationControls();
    }
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

  async function validateActiveBook() {
    if (!state.project?.path || !bookProject()) return;
    await runBookTask(() => startBookValidation(state.project.path), {
      successMessage: t("bookValid"),
      showProblems: true,
    });
  }

  function renderFullBookPreview(html) {
    const modalManager = getModalManager();
    const parsed = new DOMParser().parseFromString(String(html || ""), "text/html");
    const content = (parsed.querySelector(".md2pdf-article") || parsed.body).cloneNode(true);
    // This is a review of the saved chapters, not the publication layout. Keep
    // the ordered contents/references while leaving cover and watermark in PDF.
    content
      .querySelectorAll(":scope > .md2pdf-cover, :scope > .md2pdf-watermark")
      .forEach((element) => element.remove());
    const dialog = $("#book-review-modal");
    const container = $("#book-review-document");
    const token = requestId("book-review");
    container.dataset.reviewToken = token;
    container.dir =
      parsed.body.getAttribute("dir") || parsed.documentElement.getAttribute("dir") || "auto";
    container.lang = parsed.documentElement.lang || "";
    container.replaceChildren();
    // Full renderer styles target html/body and must never escape into the desktop
    // shell. Whole-book review does not replace the active chapter's comparison
    // pane or change its editing mode.
    container.append(safePreviewHtml(content.innerHTML, "book-review-"));
    $("#book-review-project").textContent =
      bookProject()?.title || state.project?.name || t("bookProject");
    $("#close-book-review").onclick = () => modalManager.close(dialog);
    $("#book-review-done").onclick = () => modalManager.close(dialog);
    modalManager.open(dialog, {
      initialFocus: "#close-book-review",
      returnFocus: $("#book-preview"),
      onClose: () => {
        container.replaceChildren();
        delete container.dataset.reviewToken;
      },
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
    await runBookTask(
      () =>
        startBookExport({
          projectPath: project.path,
          outputPath,
        }),
      {
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
      },
    );
  }

  return {
    setBookOperationStatus,
    syncBookOperationControls,
    cancelActiveBookOperation,
    invalidateBookTaskForProjectChange,
    renderBookOutputResult,
    openBookOutput,
    validateActiveBook,
    previewActiveBook,
    exportActiveBook,
  };
}
