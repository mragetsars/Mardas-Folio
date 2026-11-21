import { documentDirty } from "../../core/documents.mjs";
import { compactDocumentLocation } from "../../core/path-display.mjs";
import { spriteIcon } from "../../ui/icons.mjs";

export function createDocumentTabs({
  state,
  query: $,
  activeDocument,
  activateDocument,
  requestCloseDocument,
  closeCompactDrawer,
  setTruncatableText,
  t,
}) {
  function orderedTabs() {
    const tabs = state.documents;
    const byId = new Map(tabs.map((tab) => [tab.id, tab]));
    state.tabOrder = state.tabOrder.filter((id) => byId.has(id));
    for (const tab of tabs) if (!state.tabOrder.includes(tab.id)) state.tabOrder.push(tab.id);
    return state.tabOrder.map((id) => byId.get(id));
  }

  function tabElement(model) {
    const isActive = model.id === state.activeDocumentId;
    const tabs = orderedTabs();
    const tab = window.document.createElement("div");
    tab.className = `document-tab${isActive ? " active" : ""}${documentDirty(model) ? " dirty" : ""}`;
    tab.dataset.documentId = model.id;
    tab.innerHTML = `<button class="tab-activate" type="button" role="tab"><i class="dirty-dot"></i><span class="tab-name"></span></button><button class="tab-close" type="button" aria-label="${t("close")}"></button>`;
    tab.querySelector(".tab-close").append(spriteIcon("close"));
    setTruncatableText(tab.querySelector(".tab-name"), model.title);
    const activate = tab.querySelector(".tab-activate");
    activate.tabIndex = isActive ? 0 : -1;
    activate.setAttribute("aria-selected", String(isActive));
    const select = (target, focus = "editor") => activateDocument(target.id, { focus });
    activate.addEventListener("click", () => select(model));
    activate.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select(model);
        return;
      }
      const index = tabs.findIndex((item) => item.id === model.id);
      let target = null;
      const rtl = document.documentElement.dir === "rtl";
      if (event.key === (rtl ? "ArrowRight" : "ArrowLeft") || event.key === "ArrowUp")
        target = tabs[(index - 1 + tabs.length) % tabs.length];
      if (event.key === (rtl ? "ArrowLeft" : "ArrowRight") || event.key === "ArrowDown")
        target = tabs[(index + 1) % tabs.length];
      if (event.key === "Home") target = tabs[0];
      if (event.key === "End") target = tabs.at(-1);
      if (!target) return;
      event.preventDefault();
      void select(target, "tab");
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
    container.replaceChildren(...orderedTabs().map(tabElement));
    renderFileNavigator();
  }

  function revealActiveTab() {
    const strip = $("#document-tabs");
    const active = strip?.querySelector(".document-tab.active");
    if (!active || !strip.clientWidth) return;
    const bounds = strip.getBoundingClientRect();
    const tab = active.getBoundingClientRect();
    if (tab.left < bounds.left) strip.scrollBy({ left: tab.left - bounds.left });
    else if (tab.right > bounds.right) strip.scrollBy({ left: tab.right - bounds.right });
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
      button.innerHTML =
        '<i aria-hidden="true"></i><span><strong></strong><small dir="auto"></small></span>';
      button.querySelector("i").append(spriteIcon("file"));
      button.querySelector("strong").textContent = model.title;
      button.querySelector("small").textContent = model.path
        ? compactDocumentLocation(model.path, { projectPath: model.projectPath })
        : t("unsavedDocument");
      button.querySelector("small").title = model.path || t("unsavedDocument");
      button.title = `${model.title}\n${model.path || t("unsavedDocument")}${documentDirty(model) ? `\n${t("unsaved")}` : ""}`;
      button.setAttribute("aria-label", button.title);
      button.addEventListener("click", async () => {
        await activateDocument(model.id);
        closeCompactDrawer("files");
      });
      list.append(button);
    }
  }
  return { orderedTabs, renderDocumentTabs, revealActiveTab, renderFileNavigator };
}
