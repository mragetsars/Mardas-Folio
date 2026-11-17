import { invoke } from "../../adapters/tauri.mjs";
import { buildDocumentParams } from "./export-request.mjs";
import { spriteIcon } from "../../ui/icons.mjs";

export function createExportController({
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
  refreshPreviewIfDirty,
}) {
  const STATUS_SYMBOLS = {
    idle: "file",
    notice: "info",
    working: "refresh",
    success: "check",
    warning: "alert",
    error: "alert",
  };

  let exportFeedback = { kind: "idle" };
  let exportActionFocus = null;

  function setExportStatus(kind, titleKey, details = {}) {
    exportFeedback = { kind, titleKey, ...details };
    renderExportStatus();
  }

  function renderExportStatus() {
    const { kind, titleKey, messageKey, message, diagnostics = [] } = exportFeedback;
    const title = titleKey ? t(titleKey) : "";
    const copy = message ?? (messageKey ? t(messageKey) : "");
    $("#export-feedback").dataset.state = kind;
    $("#status-symbol").replaceChildren(
      ...(kind === "idle" ? [] : [spriteIcon(STATUS_SYMBOLS[kind])]),
    );
    $("#status-title").textContent = title;
    $("#status-message").textContent = copy;
    $("#status-message").title = copy;
    $("#export-show-details").hidden = kind !== "error" && diagnostics.length === 0;
    $("#export-details-message").textContent = [title, copy].filter(Boolean).join(" — ");
    const container = $("#diagnostics");
    container.replaceChildren();
    container.hidden = diagnostics.length === 0;
    for (const diagnostic of diagnostics) {
      const item = document.createElement("li");
      item.dataset.severity = diagnostic.severity || "info";
      item.dir = "auto";
      const location = diagnostic.line ? ` · ${diagnostic.line}:${diagnostic.column || 1}` : "";
      item.textContent = `${diagnostic.code || ""}${location} — ${diagnostic.message || ""}`;
      container.append(item);
    }
  }

  function invalidateExportStatus() {
    if (exportFeedback.kind === "idle") return;
    hideExportResult();
    setExportStatus("idle");
  }

  function setExportProgress(percent) {
    $("#progress-bar").value = percent;
    $("#progress-label").textContent = `${percent}%`;
  }

  function syncExportControls() {
    const busy = Boolean(state.activeRequestId);
    $("#export-back").disabled = busy;
    $("#export-inspector-controls").disabled = busy;
    $("#export-form").setAttribute("aria-busy", String(busy));
    $("#preview-choose-source").disabled = busy;
    $("#choose-output").disabled = busy || !state.sourcePath;
    $("#validate-button").disabled = busy || !state.sourcePath || !state.outputPath;
    $("#export-button").disabled = $("#validate-button").disabled;
  }

  function working(enabled, mode = "render") {
    const cancel = $("#cancel-button");
    const focused = document.activeElement;
    if (enabled)
      exportActionFocus =
        focused === $("#validate-button") || focused === $("#export-button") ? focused : null;
    syncExportControls();
    cancel.disabled = false;
    cancel.hidden = !enabled;
    $("#progress-wrap").hidden = !enabled;
    if (enabled) {
      setExportProgress(0);
      setExportStatus("working", mode === "validate" ? "validatingTitle" : "renderingTitle", {
        messageKey: mode === "validate" ? "validatingMessage" : "renderingMessage",
      });
      if (exportActionFocus) cancel.focus({ preventScroll: true });
    } else {
      if (focused === cancel || focused === document.body)
        exportActionFocus?.focus({ preventScroll: true });
      exportActionFocus = null;
      refreshPreviewIfDirty();
    }
  }

  function markExportCancelled() {
    setExportStatus("notice", null, { messageKey: "operationCancelled" });
  }

  function exportErrorCode(payload) {
    return payload?.application_code || payload?.data?.application_code || payload?.code;
  }

  async function validateExportDocument() {
    if (state.activeRequestId || !exportSelectionValid()) return;
    const id = requestId("validate");
    const params = buildDocumentParams({
      sourcePath: state.sourcePath,
      outputPath: state.outputPath,
      options: exportOverrides(),
    });
    state.activeRequestId = id;
    state.cancelledExportRequestId = null;
    hideExportResult();
    working(true, "validate");
    try {
      await releaseEngineForJob();
      if (state.cancelledExportRequestId === id) {
        markExportCancelled();
        return;
      }
      const result = await invoke("sidecar_request", {
        request_id: id,
        method: "validate.document",
        params,
      });
      const diagnostics = Array.isArray(result?.diagnostics) ? result.diagnostics : [];
      if (!result?.ok)
        setExportStatus("error", "invalidTitle", { messageKey: "invalidMessage", diagnostics });
      else if (diagnostics.some((item) => item.severity === "warning")) {
        setExportStatus("warning", "exportCheckedWithWarnings", {
          messageKey: "exportCheckedWithWarningsHelp",
          diagnostics,
        });
      } else setExportStatus("success", "validTitle", { diagnostics });
    } catch (error) {
      const payload = errorPayload(error);
      if (exportErrorCode(payload) === "MARDAS-JOB-CANCELLED") {
        markExportCancelled();
      } else {
        setExportStatus("error", "exportCheckFailed", { message: errorText(error) });
      }
    } finally {
      state.activeRequestId = null;
      working(false);
    }
  }

  async function exportDocument(event) {
    event?.preventDefault();
    if (state.activeRequestId || !exportSelectionValid()) return;
    const id = requestId("render");
    const params = buildDocumentParams({
      sourcePath: state.sourcePath,
      outputPath: state.outputPath,
      options: exportOverrides(),
    });
    params.create_only = true;
    state.activeRequestId = id;
    state.cancelledExportRequestId = null;
    hideExportResult();
    working(true);
    let focusOutput = false;
    try {
      await releaseEngineForJob();
      if (state.cancelledExportRequestId === id) {
        markExportCancelled();
        return;
      }
      const inspection = await invoke("sidecar_request", {
        request_id: requestId("output-check"),
        method: "publication.inspect_output",
        params: { output_path: params.output_path },
      });
      if (state.cancelledExportRequestId === id) {
        markExportCancelled();
        return;
      }
      if (inspection?.exists) {
        setExportStatus("error", "errorTitle", { messageKey: "outputExistsChooseNew" });
        focusOutput = true;
        return;
      }
      const result = await invoke("sidecar_request", {
        request_id: id,
        method: "render.document",
        params,
      });
      state.outputResult = result;
      const resultPath = result.output_path || state.outputPath;
      setExportStatus("success", "successTitle");
      showExportResult(resultPath);
      saveRecent(state.sourcePath);
    } catch (error) {
      const payload = errorPayload(error);
      const code = exportErrorCode(payload);
      if (code === "MARDAS-JOB-CANCELLED") {
        markExportCancelled();
      } else if (code === "MARDAS-OUTPUT-EXISTS") {
        setExportStatus("error", "errorTitle", { messageKey: "outputExistsChooseNew" });
        focusOutput = true;
      } else {
        const diagnostics = Array.isArray(payload?.details?.diagnostics)
          ? payload.details.diagnostics
          : [];
        setExportStatus("error", "errorTitle", { message: errorText(error), diagnostics });
      }
    } finally {
      state.activeRequestId = null;
      working(false);
      if (focusOutput) $("#choose-output").focus();
    }
  }

  async function cancelExport() {
    const id = state.activeRequestId;
    if (!id || state.cancelledExportRequestId === id) return;
    const runningStatus = exportFeedback;
    state.cancelledExportRequestId = id;
    $("#cancel-button").disabled = true;
    setExportStatus("working", null, { messageKey: "cancellingOperation" });
    try {
      await invoke("sidecar_cancel", { request_id: id });
    } catch (error) {
      if (state.activeRequestId === id) {
        state.cancelledExportRequestId = null;
        $("#cancel-button").disabled = false;
        exportFeedback = runningStatus;
        renderExportStatus();
        toast(errorText(error), "error");
      }
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

  function updateExportMessage(message) {
    exportFeedback.message = message;
    $("#status-message").textContent = message;
    $("#status-message").title = message;
  }
  return {
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
  };
}
