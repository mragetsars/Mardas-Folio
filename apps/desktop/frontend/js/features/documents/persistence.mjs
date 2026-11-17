import { invoke } from "../../adapters/tauri.mjs";
import { saveProjectFile } from "../../adapters/project-api.mjs";
import { saveDocument, saveTextDocument } from "../../adapters/authoring-api.mjs";
import { closeDocument, documentDirty, findSavePathCollision, markDocumentSaved, pathKey } from "../../core/documents.mjs";
import { recoveryKey, removeRecovery, saveRecovery } from "./recovery.mjs";

export function createDocumentPersistence({ state, query: $, getEditor, activeDocument, isMarkdownModel, saveCoordinator, activateDocument, activateStartTab, focusDocument, saveRecent, persistSession, renderWorkspace, renderDocumentTabs, refreshActiveProject, setSaveState, askConfirmation, t, toast, errorText, errorPayload }) {
  async function saveActiveDocument({ saveAs = false, force = false } = {}) {
    if (getEditor()?.commitPendingDrafts?.() === false) return false;
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
    const hasUnsavedWork = model.persisted ? documentDirty(model) : model.content !== "";
    if (hasUnsavedWork) {
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
    if (wasActive && result.nextId) await activateDocument(result.nextId);
    else if (wasActive && state.startTabs.length) activateStartTab(state.startTabs.at(-1).id);
    else if (!state.documents.length) focusDocument();
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
  return { saveActiveDocument, persistDocumentModel, requestCloseDocument, cancelRecoveryTimer, scheduleRecovery };
}
