export function createPreviewSanitizer({ t }) {
  function isRelativeMarkdownDocumentHref(value) {
    const path = String(value || "").split(/[?#]/, 1)[0];
    try {
      return /\.(?:md|markdown)$/i.test(decodeURIComponent(path));
    } catch {
      return false;
    }
  }

  function safePreviewHtml(value, prefix = "preview-") {
    const template = document.createElement("template");
    template.innerHTML = String(value || "");
    template.content
      .querySelectorAll(
        "script,style,iframe,object,embed,meta,base,link,form,button,select,option,textarea",
      )
      .forEach((element) => element.remove());
    const idMap = new Map();
    // Rendered headings and notes share the page with the application shell.
    // Reserve shell IDs so a heading named "Document" cannot shadow the
    // reading-document or preview-document containers.
    const reservedIds = new Set(
      [...document.querySelectorAll("[id]")]
        .filter(
          (element) =>
            !element.closest(".document-content") || element.matches(".document-content"),
        )
        .map((element) => element.id),
    );
    template.content.querySelectorAll("[id]").forEach((element) => {
      const original = element.id;
      let prefixed = `${prefix}${original}`;
      while (reservedIds.has(prefixed))
        prefixed = `${prefix}content-${prefixed.slice(prefix.length)}`;
      reservedIds.add(prefixed);
      if (!idMap.has(original)) idMap.set(original, prefixed);
      element.dataset.previewSourceId = original;
      element.id = prefixed;
    });
    template.content.querySelectorAll("*").forEach((element) => {
      const reservedClasses = new Set([
        "active",
        "hidden",
        "modal",
        "toast",
        "view",
        "sidebar-panel",
        "source-active",
      ]);
      for (const className of [...element.classList]) {
        if (reservedClasses.has(className)) element.classList.remove(className);
      }
      if (element.matches("a.md2pdf-local-link-blocked")) {
        const href = element.getAttribute("data-md2pdf-source") || "";
        element.removeAttribute("data-md2pdf-source");
        if (isRelativeMarkdownDocumentHref(href)) {
          element.dataset.mardasMarkdownHref = href;
          element.setAttribute("role", "link");
          element.setAttribute("tabindex", "0");
          element.removeAttribute("aria-disabled");
          element.setAttribute("title", t("openLinkedMarkdown"));
          element.setAttribute(
            "aria-label",
            `${element.textContent.trim()} — ${t("openLinkedMarkdown")}`,
          );
        } else {
          element.setAttribute("aria-disabled", "true");
          element.setAttribute("title", t("previewLinkUnavailable"));
          element.setAttribute(
            "aria-label",
            `${element.textContent.trim()} — ${t("previewLinkUnavailable")}`,
          );
        }
      }
      for (const attribute of [...element.attributes]) {
        const name = attribute.name.toLowerCase();
        if (
          name.startsWith("on") ||
          [
            "action",
            "autofocus",
            "background",
            "contenteditable",
            "data",
            "download",
            "draggable",
            "formaction",
            "ping",
            "poster",
            "srcdoc",
            "srcset",
            "style",
            "target",
            "xlink:href",
          ].includes(name)
        ) {
          element.removeAttribute(attribute.name);
          continue;
        }
        if (name === "href") {
          if (attribute.value.startsWith("#")) {
            let target = attribute.value.slice(1);
            try {
              target = decodeURIComponent(target);
            } catch {
              /* Keep malformed fragments inert. */
            }
            element.setAttribute("href", `#${idMap.get(target) || `${prefix}${target}`}`);
          } else {
            element.removeAttribute("href");
            element.setAttribute("aria-disabled", "true");
            element.setAttribute("title", t("previewLinkUnavailable"));
            element.setAttribute(
              "aria-label",
              `${element.textContent.trim()} — ${t("previewLinkUnavailable")}`,
            );
            continue;
          }
        }
        if (name === "src" && !/^\s*data:image\//i.test(attribute.value)) {
          element.removeAttribute(attribute.name);
          continue;
        }
        if (["for", "aria-labelledby", "aria-describedby"].includes(name)) {
          const rewritten = attribute.value
            .split(/\s+/)
            .map((id) => idMap.get(id) || `${prefix}${id}`)
            .join(" ");
          element.setAttribute(attribute.name, rewritten);
        }
        // Prefixing ids also has to prefix what points at them. A Mermaid
        // arrowhead is a `<marker id=…>` referenced by `marker-end="url(#…)"`,
        // so rewriting one without the other left every diagram without arrows.
        if (
          [
            "marker-start",
            "marker-mid",
            "marker-end",
            "clip-path",
            "mask",
            "fill",
            "stroke",
            "filter",
          ].includes(name) &&
          /url\s*\(/i.test(attribute.value)
        ) {
          const localReference = /url\(\s*["']?#([^\s)"']+)["']?\s*\)/g;
          if (/url\s*\(/i.test(attribute.value.replace(localReference, ""))) {
            element.removeAttribute(attribute.name);
            continue;
          }
          element.setAttribute(
            attribute.name,
            attribute.value.replace(
              localReference,
              (whole, id) => `url(#${idMap.get(id) || `${prefix}${id}`})`,
            ),
          );
        }
      }
      if (element instanceof HTMLInputElement) {
        if (element.type !== "checkbox") {
          element.remove();
        } else {
          element.disabled = true;
          element.tabIndex = -1;
        }
      }
      if (element.classList.contains("md2pdf-mermaid-svg")) {
        const viewBox = (element.getAttribute("viewBox") || "")
          .trim()
          .split(/[\s,]+/)
          .map(Number);
        if (viewBox.length === 4 && viewBox.every(Number.isFinite) && viewBox[2] > 0) {
          element.setAttribute("width", String(Math.min(viewBox[2], 960)));
        }
      }
    });
    return template.content;
  }
  return { safePreviewHtml };
}
