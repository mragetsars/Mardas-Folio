import {
  addBookChapter,
  duplicateBookChapter,
  reorderBookChapters,
  removeBookChapter,
} from "../../adapters/book-api.mjs";
import { spriteIcon } from "../../ui/icons.mjs";

export function createBookChapters({
  state,
  query: $,
  getModalManager,
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
}) {
  function openChapterModal(mode, chapter = null) {
    state.chapterModalMode = mode;
    state.chapterModalPath = chapter?.path || null;
    const duplicate = mode === "duplicate";
    $("#chapter-modal-title").textContent = t(duplicate ? "duplicateChapter" : "addChapter");
    $("#chapter-modal-description").textContent = t("addChapterHelp");
    $("#chapter-title-input").value = duplicate
      ? `${chapter?.title || chapter?.path || t("chapterTitle")} ${state.locale === "fa" ? "کپی" : "Copy"}`
      : "";
    getModalManager().open($("#chapter-modal"), {
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
    getModalManager().close($("#chapter-modal"));
  }

  function bookProject() {
    return state.project?.book || null;
  }

  async function submitChapterModal(event) {
    event.preventDefault();
    const project = state.project;
    const title = $("#chapter-title-input").value.trim();
    if (!project?.path || !project.config_sha256 || !title) return;
    const projectContext = currentProjectContext();
    const mode = state.chapterModalMode;
    const submit = event.submitter || $("#chapter-form button[type='submit']");
    submit.disabled = true;
    try {
      const result =
        mode === "duplicate"
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
      if (!projectContextIsCurrent(projectContext)) return;
      applyProjectPayload(result);
      closeChapterModal();
      const created = result.created_chapter?.path;
      if (created) await openProjectRelativeFile(created);
      toast(t(mode === "duplicate" ? "chapterDuplicated" : "chapterAdded"), "success");
    } catch (error) {
      if (projectContextIsCurrent(projectContext)) toast(errorText(error), "error");
    } finally {
      submit.disabled = false;
    }
  }

  async function saveBookOrder(orderedPaths) {
    const project = state.project;
    if (!project?.path || !project.config_sha256) return;
    const projectContext = currentProjectContext();
    try {
      const result = await reorderBookChapters({
        projectPath: project.path,
        orderedPaths,
        expectedConfigSha256: project.config_sha256,
      });
      if (!projectContextIsCurrent(projectContext)) return;
      applyProjectPayload(result);
      toast(t("chapterOrderSaved"), "success");
    } catch (error) {
      if (projectContextIsCurrent(projectContext)) toast(errorText(error), "error");
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
    const projectContext = currentProjectContext();
    const confirmed = await askConfirmation({
      title: t("removeFromBook"),
      message: t("confirmRemoveChapter"),
      confirmLabel: t("removeFromBook"),
      danger: true,
    });
    if (!confirmed || !projectContextIsCurrent(projectContext)) return;
    try {
      const result = await removeBookChapter({
        projectPath: project.path,
        relativePath: chapter.path,
        expectedConfigSha256: project.config_sha256,
      });
      if (!projectContextIsCurrent(projectContext)) return;
      applyProjectPayload(result);
      toast(t("chapterRemoved"), "success");
    } catch (error) {
      if (projectContextIsCurrent(projectContext)) toast(errorText(error), "error");
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
      up: "chevron-up",
      down: "chevron-down",
      duplicate: "duplicate",
      remove: "close",
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
  return { openChapterModal, closeChapterModal, bookProject, submitChapterModal, bookChapterRow };
}
