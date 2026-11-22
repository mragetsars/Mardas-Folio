import { invoke } from "../../adapters/tauri.mjs";
import { createBookProject } from "../../adapters/book-api.mjs";
import { pathKey } from "../../core/documents.mjs";

export function createBookCreation({
  state,
  query: $,
  getModalManager,
  invalidateBookTaskForProjectChange,
  applyProjectPayload,
  onBookOpened = () => {},
  showView,
  activateSidebar,
  openProjectRelativeFile,
  t,
  toast,
  errorText,
}) {
  let createSequence = 0;
  let createOnShelf = false;

  function folderNameFromTitle(value) {
    const normalized = String(value || "")
      .trim()
      .toLocaleLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60);
    return normalized || "mardas-book";
  }

  function openNewBookModal({ stayInLibrary = false } = {}) {
    createOnShelf = stayInLibrary;
    const titleInput = $("#book-project-title-input");
    const folderInput = $("#book-project-folder-input");
    titleInput.value = "";
    folderInput.value = "";
    folderInput.dataset.userEdited = "";
    $("#book-project-parent-input").value = "";
    $("#book-project-language").value = state.locale === "fa" ? "fa-IR" : "en-US";
    $("#book-project-direction").value = state.locale === "fa" ? "rtl" : "ltr";
    getModalManager().open($("#book-project-modal"), {
      initialFocus: "#book-project-title-input",
      onClose: () => {
        createSequence += 1;
        $("#book-project-form").reset();
        folderInput.dataset.userEdited = "";
      },
    });
  }

  function closeNewBookModal() {
    getModalManager().close($("#book-project-modal"));
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
    const sequence = ++createSequence;
    const expectedProjectPath = state.project?.path || null;
    const expectedProjectGeneration = state.projectGeneration;
    const stayInLibrary = createOnShelf;
    const handoff = stayInLibrary ? Promise.resolve() : invalidateBookTaskForProjectChange();
    try {
      await handoff;
      if (
        sequence !== createSequence ||
        state.projectGeneration !== expectedProjectGeneration ||
        pathKey(state.project?.path) !== pathKey(expectedProjectPath)
      )
        return;
      const project = await createBookProject({
        parentPath,
        folderName,
        title,
        language: $("#book-project-language").value,
        direction: $("#book-project-direction").value,
      });
      if (
        sequence !== createSequence ||
        state.projectGeneration !== expectedProjectGeneration ||
        pathKey(state.project?.path) !== pathKey(expectedProjectPath)
      )
        return;
      if (!stayInLibrary) applyProjectPayload(project);
      await onBookOpened(project);
      if (sequence !== createSequence) return;
      closeNewBookModal();
      if (!stayInLibrary) {
        showView("workspace");
        activateSidebar("book", { reveal: false });
        const first = project.book?.chapters?.[0]?.path;
        if (first) await openProjectRelativeFile(first);
      }
      toast(t("bookCreated"), "success");
    } catch (error) {
      if (sequence === createSequence) toast(errorText(error), "error");
    } finally {
      submit.disabled = false;
    }
  }

  return {
    folderNameFromTitle,
    openNewBookModal,
    closeNewBookModal,
    chooseBookParent,
    submitNewBookProject,
  };
}
