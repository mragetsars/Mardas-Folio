import { filterCommands } from "../core/command-palette.mjs";
import { spriteIcon } from "./icons.mjs";
/** Owns this feature's DOM interactions; cross-feature actions are injected. */
export function createCommandPalette({ query: $, queryAll: $$, getModalManager, commandDefinitions, t, toast, errorText }) {
  const state = { commandIndex: 0, visibleCommands: [] };
  function resetCommandSelection() { state.commandIndex = 0; }
  function highlightCommand(index) {
    const length = state.visibleCommands.length;
    if (!length) {
      state.commandIndex = 0;
      return;
    }
    state.commandIndex = Math.max(0, Math.min(length - 1, Number(index) || 0));
    $$("#command-list .command-item").forEach((item, itemIndex) => {
      const active = itemIndex === state.commandIndex;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", String(active));
    });
    const active = $("#command-list .command-item.active");
    if (active) $("#command-query").setAttribute("aria-activedescendant", active.id);
    else $("#command-query").removeAttribute("aria-activedescendant");
    $("#command-list .command-item.active")?.scrollIntoView?.({ block: "nearest" });
  }

  function renderCommandPalette() {
    const query = $("#command-query")?.value || "";
    state.visibleCommands = filterCommands(commandDefinitions(), query, 12);
    state.commandIndex = Math.max(0, Math.min(state.commandIndex, Math.max(0, state.visibleCommands.length - 1)));
    const container = $("#command-list");
    container.replaceChildren();
    if (!state.visibleCommands.length) {
      $("#command-query").removeAttribute("aria-activedescendant");
      const empty = document.createElement("div");
      empty.className = "command-empty";
      empty.textContent = t("noCommands");
      container.append(empty);
      return;
    }
    state.visibleCommands.forEach((command, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `command-item${index === state.commandIndex ? " active" : ""}`;
      button.dataset.commandId = command.id;
      button.id = `command-option-${command.id}`;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(index === state.commandIndex));
      button.innerHTML = "<i></i><span><strong></strong></span><kbd></kbd>";
      button.querySelector("i").replaceChildren(spriteIcon(command.symbol || "file"));
      button.querySelector("strong").textContent = command.label;
      const shortcut = button.querySelector("kbd");
      shortcut.textContent = command.shortcut || "";
      shortcut.classList.toggle("hidden", !command.shortcut);
      button.addEventListener("mouseenter", () => highlightCommand(index));
      button.addEventListener("click", () => runCommand(command));
      container.append(button);
    });
    container.querySelector(".command-item.active")?.scrollIntoView?.({ block: "nearest" });
    const active = container.querySelector(".command-item.active");
    if (active) $("#command-query").setAttribute("aria-activedescendant", active.id);
  }

  function openCommandPalette() {
    if (getModalManager().hasOpenModal()) return;
    state.commandIndex = 0;
    $("#command-query").value = "";
    renderCommandPalette();
    $("#command-query").setAttribute("aria-expanded", "true");
    getModalManager().open($("#command-modal"), {
      initialFocus: "#command-query",
      onClose: resetCommandPaletteA11y,
    });
  }

  function resetCommandPaletteA11y() {
    $("#command-query").setAttribute("aria-expanded", "false");
    $("#command-query").removeAttribute("aria-activedescendant");
  }

  function closeCommandPalette() {
    getModalManager().close($("#command-modal"));
  }

  async function runCommand(command = state.visibleCommands[state.commandIndex]) {
    if (!command) return;
    closeCommandPalette();
    try {
      await command.run?.();
    } catch (error) {
      toast(errorText(error), "error");
    }
  }

  function commandKeydown(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const length = state.visibleCommands.length;
      if (length) highlightCommand((state.commandIndex + direction + length) % length);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      runCommand();
    }
  }
  return { renderCommandPalette, openCommandPalette, closeCommandPalette, commandKeydown, resetCommandSelection };
}
