/** One content renderer for reading, side preview and whole-book review. */
export function mountDocumentContent(container, payload, {
  sanitize, prefix = "preview-", sourceEntries = [], onSourceJump,
  sourceJumpLabel = (line) => `Line ${line}`,
} = {}) {
  const document = container.ownerDocument;
  const fragment = sanitize(
    `${payload?.body_html || ""}${payload?.reference_lists_html || ""}${payload?.bibliography_html || ""}`,
    prefix,
  );
  const lines = new Map(sourceEntries.map((entry) => [entry.id, entry.line]));
  for (const heading of fragment.querySelectorAll("h1,h2,h3,h4,h5,h6")) {
    if (!heading.hasAttribute("dir")) heading.dir = "auto";
    const sourceId = heading.dataset.previewSourceId || heading.id.slice(prefix.length);
    const line = Number(heading.dataset.sourceLine) || lines.get(sourceId);
    if (!line) continue;
    heading.dataset.sourceLine = String(line);
    if (!onSourceJump) continue;
    // Keep the heading and its real links semantic. Source navigation is a
    // separate control, whose gutter position does not alter document wrapping.
    const button = document.createElement("button");
    button.type = "button";
    button.className = "document-source-jump";
    button.setAttribute("aria-label", sourceJumpLabel(line));
    button.title = sourceJumpLabel(line);
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("class", "ui-icon");
    icon.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#icon-source");
    icon.append(use);
    button.append(icon);
    button.addEventListener("click", () => onSourceJump(line));
    heading.append(button);
  }
  container.replaceChildren(fragment);
  container.classList.add("document-content");
  container.dir = payload?.direction === "rtl" || payload?.direction === "ltr" ? payload.direction : "auto";
  if (payload?.pygments_css) {
    const style = document.createElement("style");
    style.textContent = payload.pygments_css;
    container.prepend(style);
  }
}
