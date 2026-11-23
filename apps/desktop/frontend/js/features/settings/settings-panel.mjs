import { foldForFilter } from "../../core/persian.mjs";

export function createSettingsPanel(form) {
  const search = form.querySelector("#settings-search");
  const clear = form.querySelector("#settings-clear-search");
  const nav = form.querySelector(".settings-nav");
  const buttons = [...nav.querySelectorAll("button[aria-controls]")];
  const content = form.querySelector("#settings-sections");
  const empty = form.querySelector("#settings-empty");
  const sections = [...content.querySelectorAll(".settings-section")].map((section) => ({
    section,
    heading: section.querySelector("h3"),
    rows: [...section.querySelectorAll(".settings-row")],
  }));
  let activeSection = "settings-appearance";

  function render() {
    const terms = foldForFilter(search.value).split(/\s+/).filter(Boolean);
    const searching = terms.length > 0;
    let hasMatch = false;
    for (const { section, heading, rows } of sections) {
      for (const row of rows) {
        const searchableText = foldForFilter(
          `${heading.textContent} ${row.dataset.settingsTerms || ""} ${row.textContent} ${[...row.querySelectorAll("input[type=radio]")].map((radio) => radio.getAttribute("aria-label")).join(" ")}`,
        );
        row.hidden = searching && !terms.every((term) => searchableText.includes(term));
      }
      const show = searching ? rows.some((row) => !row.hidden) : section.id === activeSection;
      section.hidden = !show;
      hasMatch ||= show;
    }
    for (const button of buttons) {
      if (!searching && button.getAttribute("aria-controls") === activeSection)
        button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    }
    clear.hidden = !search.value;
    empty.hidden = hasMatch;
    content.scrollTop = 0;
  }

  function showSection(section = activeSection) {
    activeSection = section;
    search.value = "";
    render();
  }

  nav.addEventListener("click", (event) => {
    const button = event.target.closest("button[aria-controls]");
    if (button) showSection(button.getAttribute("aria-controls"));
  });
  search.addEventListener("input", render);
  search.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) event.preventDefault();
  });
  clear.addEventListener("click", () => {
    showSection();
    search.focus();
  });
  // A draft can contain an invalid number after its row has been filtered out.
  form.addEventListener(
    "invalid",
    (event) => {
      const section = event.target.closest(".settings-section");
      if (section && event.target.closest("[hidden]")) showSection(section.id);
    },
    true,
  );

  return { showSection };
}
