import { filterNavigationEntries } from "./document-navigation.mjs";

/** One keyboard picker, with distinct file and in-document heading scopes. */
export function createNavigationPicker({ manager, getEntries, onChoose, t, documentRef = document }) {
  const modal = documentRef.createElement("div");
  modal.id = "navigation-modal";
  modal.className = "modal hidden";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-hidden", "true");
  modal.setAttribute("aria-labelledby", "navigation-title");
  modal.innerHTML = `<div class="modal-card command-card navigation-card">
    <div class="modal-heading"><h2 id="navigation-title"></h2><button id="navigation-close" class="icon-button" type="button">×</button></div>
    <input id="navigation-query" type="search" role="combobox" aria-autocomplete="list" aria-controls="navigation-list" aria-expanded="false" autocomplete="off" spellcheck="false">
    <div id="navigation-list" class="command-list" role="listbox"></div>
    <div class="command-footer"><span id="navigation-help"></span><kbd>↑ ↓</kbd><kbd>Enter</kbd><kbd>Esc</kbd></div>
  </div>`;
  documentRef.body.append(modal);
  const query = modal.querySelector("#navigation-query");
  const list = modal.querySelector("#navigation-list");
  let scope = "files";
  let index = 0;
  let entries = [];

  function highlight(next) {
    index = Math.max(0, Math.min(entries.length - 1, next));
    for (const [position, button] of [...list.querySelectorAll(".navigation-item")].entries()) {
      const selected = position === index;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", String(selected));
    }
    const active = entries.length ? list.children[index] : null;
    if (active) {
      query.setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({ block: "nearest" });
    } else query.removeAttribute("aria-activedescendant");
  }

  function choose(entry) {
    if (!entry) return;
    manager.close(modal, { restoreFocus: false });
    void onChoose(entry, scope);
  }

  function render() {
    entries = filterNavigationEntries(getEntries(scope), query.value);
    list.replaceChildren();
    if (!entries.length) {
      const empty = documentRef.createElement("p");
      empty.className = "command-empty";
      empty.textContent = t(scope === "headings" ? "noHeadingsFound" : "noFilesFound");
      list.append(empty);
    }
    entries.forEach((entry, position) => {
      const button = documentRef.createElement("button");
      button.className = "command-item navigation-item";
      button.type = "button";
      button.id = `navigation-option-${position}`;
      button.dataset.navigationId = entry.id;
      button.setAttribute("role", "option");
      button.tabIndex = -1;
      const symbol = documentRef.createElement("i");
      symbol.textContent = scope === "headings" ? `H${entry.level}` : entry.dirty ? "●" : "◇";
      symbol.setAttribute("aria-hidden", "true");
      const text = documentRef.createElement("span");
      const title = documentRef.createElement("strong");
      title.textContent = entry.label;
      const detail = documentRef.createElement("small");
      detail.textContent = entry.detail || t("unsavedDocument");
      detail.dir = "auto";
      text.append(title, detail);
      button.append(symbol, text);
      button.title = `${entry.label}\n${entry.detail || t("unsavedDocument")}`;
      button.addEventListener("mouseenter", () => highlight(position));
      button.addEventListener("click", () => choose(entry));
      list.append(button);
    });
    highlight(index);
  }
  query.addEventListener("input", () => { index = 0; render(); });
  query.addEventListener("keydown", (event) => {
    if (["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) event.preventDefault();
    if (event.key === "ArrowDown") highlight((index + 1) % Math.max(1, entries.length));
    if (event.key === "ArrowUp") highlight((index - 1 + entries.length) % Math.max(1, entries.length));
    if (event.key === "Enter") choose(entries[index]);
  });
  modal.querySelector("#navigation-close").addEventListener("click", () => manager.close(modal));
  return {
    open(kind = "files") {
      if (manager.hasOpenModal()) return;
      scope = kind;
      index = 0;
      query.value = "";
      const title = t(kind === "headings" ? "goToHeading" : "quickOpen");
      modal.querySelector("#navigation-title").textContent = title;
      query.setAttribute("aria-label", title);
      query.placeholder = t(kind === "headings" ? "searchHeadings" : "searchOpenFiles");
      list.setAttribute("aria-label", title);
      modal.querySelector("#navigation-close").setAttribute("aria-label", t("close"));
      modal.querySelector("#navigation-help").textContent = t(kind === "headings" ? "headingPickerHelp" : "filePickerHelp");
      render();
      query.setAttribute("aria-expanded", "true");
      manager.open(modal, { initialFocus: query,
        onClose: () => { query.setAttribute("aria-expanded", "false"); query.removeAttribute("aria-activedescendant"); } });
    },
  };
}
