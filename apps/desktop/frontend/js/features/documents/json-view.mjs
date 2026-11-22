import { jsonTree, replaceScalar } from "./json-source.mjs";
import { enableDialogBackdrop } from "../../ui/dialog-backdrop.mjs";
import { spriteIcon } from "../../ui/icons.mjs";

function node(tag, text) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  return result;
}
function button(label, run, className = "button secondary") {
  const result = node("button", label);
  result.type = "button";
  result.className = className;
  result.addEventListener("click", run);
  return result;
}
export function createJsonView(host, { t, current, editable, apply, sourceMode }) {
  let previous = null;
  const batchSize = 40;
  function render(model, locale) {
    const source = model.content,
      writable = editable();
    if (
      previous?.model === model &&
      previous.source === source &&
      previous.writable === writable &&
      previous.locale === locale
    )
      return;
    const same = previous?.model === model;
    const expanded = new Set(
      same ? [...host.querySelectorAll("details[open]")].map((d) => d.dataset.path) : [],
    );
    const oldQuery = same ? host.querySelector("input[type=search]")?.value || "" : "";
    const scroll = same ? host.scrollTop : 0;
    previous = { model, source, writable, locale };
    host.replaceChildren();
    let root;
    try {
      root = jsonTree(source);
    } catch (err) {
      host.append(node("p", t(err instanceof RangeError ? "jsonLarge" : "jsonInvalid")));
      if (err instanceof SyntaxError) host.append(node("small", err.message));
      host.append(button(t("viewSource"), sourceMode));
      return;
    }
    const search = node("input"),
      tree = node("div");
    search.type = "search";
    search.value = oldQuery;
    search.dir = "auto";
    search.placeholder = t("findField");
    search.setAttribute("aria-label", search.placeholder);
    tree.className = "field-tree";
    host.append(search, tree);
    const valueOf = (value) =>
      value.type === "string"
        ? JSON.parse(source.slice(value.from, value.to))
        : source.slice(value.from, value.to);
    function pageList(parent, entries, draw) {
      let offset = 0;
      function append() {
        parent.querySelector(":scope > .json-more")?.remove();
        const end = Math.min(entries.length, offset + batchSize);
        for (; offset < end; offset++) parent.append(draw(entries[offset], offset));
        if (offset < entries.length)
          parent.append(button(t("showMore"), append, "button secondary json-more"));
      }
      append();
    }
    function field(value, key, path, depth, label) {
      if (!value.children) {
        const row = node(writable ? "button" : "div");
        row.className = "json-field";
        row.dataset.path = path;
        const name = node("span", label),
          display = node("span", valueOf(value) || t("jsonEmpty"));
        name.dir = display.dir = "auto";
        row.append(name, display);
        if (writable) {
          row.type = "button";
          row.append(spriteIcon("pencil"));
          row.onclick = () => edit(value, label, path);
        }
        return row;
      }
      const branch = node("details"),
        summary = node("summary", label),
        body = node("div");
      branch.dataset.path = path;
      body.className = "json-branch";
      summary.append(
        node("small", new Intl.NumberFormat(locale).format(value.children.length)),
        spriteIcon("chevron-down"),
      );
      branch.append(summary, body);
      let loaded = false;
      function load() {
        if (loaded || !branch.open) return;
        loaded = true;
        pageList(body, value.children, ({ key: childKey, node: child }, i) => {
          const name =
            model.libraryType === "resume" &&
            key === "basics" &&
            ["name", "email", "label", "summary"].includes(childKey)
              ? t("resume" + childKey)
              : childKey;
          return field(child, childKey, path + "/" + i, depth + 1, name);
        });
      }
      branch.open = depth === 0 || expanded.has(path) || (!same && key === "basics" && depth === 1);
      load();
      branch.ontoggle = load;
      return branch;
    }
    function show() {
      tree.replaceChildren();
      const fold = (text) => text.normalize("NFKC").toLocaleLowerCase(locale);
      const q = fold(search.value.trim());
      if (!q) {
        tree.append(field(root, "", "root", 0, t("jsonFields")));
        return;
      }
      const matches = [];
      function visit(value, names, path) {
        if (value.children) {
          value.children.forEach((entry, i) =>
            visit(entry.node, [...names, entry.key], path + "/" + i),
          );
        } else {
          const label = names.join(" / ") || t("jsonFields");
          if (fold(label + " " + valueOf(value)).includes(q)) matches.push({ value, label, path });
        }
      }
      visit(root, [], "root");
      pageList(tree, matches, ({ value, label, path }) => field(value, "", path, 0, label));
      if (!matches.length) tree.append(node("p", t("shelfNoResults")));
    }
    function edit(value, label, path) {
      const dialog = node("dialog");
      const form = node("form");
      const boolean = value.type === "boolean";
      const title = node(boolean ? "fieldset" : "label");
      dialog.className = "library-form";
      dialog.setAttribute("aria-label", label);
      let input;
      if (boolean) {
        title.className = "json-radio-group";
        title.append(node("legend", label));
        for (const raw of ["true", "false"]) {
          const option = node("label");
          const radio = node("input");
          radio.type = "radio";
          radio.name = "json-boolean";
          radio.value = raw;
          radio.checked = valueOf(value) === raw;
          if (radio.checked) input = radio;
          option.append(radio, node("span", t(raw === "true" ? "on" : "off")));
          title.append(option);
        }
      } else {
        input = node(value.type === "string" ? "textarea" : "input");
        input.value = valueOf(value);
        input.dir = "auto";
        title.append(label, input);
      }
      const error = node("p"),
        actions = node("div");
      error.setAttribute("role", "alert");
      actions.className = "library-form-actions";
      const save = node("button", t("save"));
      save.className = "button primary";
      save.type = "submit";
      actions.append(
        button(t("cancel"), () => dialog.close()),
        save,
      );
      form.append(title, error, actions);
      dialog.append(form);
      document.body.append(dialog);
      enableDialogBackdrop(dialog);
      dialog.onclose = () => {
        dialog.remove();
        (
          host.querySelector('[data-path="' + path + '"].json-field') ||
          host.querySelector("input,summary")
        )?.focus();
      };
      form.onsubmit = (e) => {
        e.preventDefault();
        if (current() !== model || model.content !== source || !editable()) {
          error.textContent = t("shelfResumeChanged");
          return;
        }
        try {
          const selected = boolean ? form.elements.namedItem("json-boolean").value : input.value;
          const raw = value.type === "string" ? JSON.stringify(selected) : selected.trim();
          const next = replaceScalar(source, value, raw);
          if (next !== source) apply(next);
          render(model, locale);
          dialog.close();
        } catch {
          error.textContent = t("jsonValueError");
        }
      };
      dialog.showModal();
      input.focus();
    }
    search.addEventListener("input", show);
    show();
    host.scrollTop = scroll;
  }
  return { render };
}
