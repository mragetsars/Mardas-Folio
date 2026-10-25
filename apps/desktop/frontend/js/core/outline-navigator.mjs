import { foldForFilter } from "./persian.mjs";

/** Build a hierarchy even when an author skips heading levels. */
export function buildOutlineTree(items = []) {
  const roots = [];
  const flat = [];
  const stack = [];
  const occurrences = new Map();
  for (const item of items) {
    const level = Number(item?.level);
    const line = Number(item?.line);
    if (!Number.isInteger(level) || level < 1 || level > 6 || !Number.isInteger(line) || line < 1) continue;
    const title = String(item?.title ?? "").trim();
    while (stack.length && stack.at(-1).level >= level) stack.pop();
    const parent = stack.at(-1) || null;
    const identity = JSON.stringify([parent?.id || "", level, title]);
    const occurrence = (occurrences.get(identity) || 0) + 1;
    occurrences.set(identity, occurrence);
    // Source lines move while writing. A title's identity must not depend on
    // its line number, otherwise every paragraph insertion unfolds the tree.
    // Code-point keys also tolerate a transient lone UTF-16 surrogate while
    // text is edited; encodeURIComponent would throw and break navigation.
    const titleKey = Array.from(title, (character) => character.codePointAt(0).toString(16)).join(".");
    const id = `${parent?.id || ""}/${level}:${titleKey}:${occurrence}`;
    const node = { id, level, line, title, depth: stack.length, parentId: parent?.id || null, children: [] };
    if (parent) parent.children.push(node);
    else roots.push(node);
    flat.push(node);
    stack.push(node);
  }
  return { roots, flat };
}

export class OutlineNavigatorModel {
  constructor({ documentLimit = 40 } = {}) {
    this.documentLimit = Math.max(1, documentLimit);
    this.documents = new Map();
    this.documentId = "";
    this.query = "";
    this.current = { roots: [], flat: [], collapsed: new Set(), line: 1, signature: "[]" };
  }

  setDocument(documentId, items = []) {
    const id = String(documentId ?? "");
    const signature = JSON.stringify(items.map(({ level, title, line }) => [level, title, line]));
    let state = this.documents.get(id);
    const changed = id !== this.documentId || !state || state.signature !== signature;
    if (!state) state = { roots: [], flat: [], collapsed: new Set(), line: 1, signature: "" };
    if (state.signature !== signature) {
      const tree = buildOutlineTree(items);
      const ids = new Set(tree.flat.map((node) => node.id));
      state = { ...state, ...tree, signature, collapsed: new Set([...state.collapsed].filter((key) => ids.has(key))) };
    }
    this.documents.delete(id);
    this.documents.set(id, state);
    while (this.documents.size > this.documentLimit) this.documents.delete(this.documents.keys().next().value);
    this.documentId = id;
    this.current = state;
    return changed;
  }

  forgetDocument(documentId) {
    this.documents.delete(String(documentId));
  }

  setQuery(query) {
    const next = String(query ?? "");
    if (next === this.query) return false;
    this.query = next;
    return true;
  }

  setActiveLine(line) {
    this.current.line = Math.max(1, Number(line) || 1);
    return this.activeNode();
  }

  activeNode() {
    const flat = this.current.flat;
    let low = 0;
    let high = flat.length - 1;
    let result = null;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (flat[middle].line <= this.current.line) {
        result = flat[middle];
        low = middle + 1;
      } else high = middle - 1;
    }
    return result;
  }

  toggle(id, expanded) {
    const node = this.current.flat.find((entry) => entry.id === id);
    if (!node?.children.length) return false;
    const next = expanded ?? this.current.collapsed.has(id);
    if (next) this.current.collapsed.delete(id);
    else this.current.collapsed.add(id);
    return true;
  }

  expandAll() { this.current.collapsed.clear(); }

  collapseAll() {
    this.current.collapsed = new Set(this.current.flat.filter((node) => node.children.length).map((node) => node.id));
  }

  visibleNodes() {
    const tokens = foldForFilter(this.query).split(/\s+/u).filter(Boolean);
    const keep = new Set();
    const matches = new Set();
    const byId = new Map(this.current.flat.map((node) => [node.id, node]));
    if (tokens.length) {
      for (const node of this.current.flat) {
        const title = foldForFilter(node.title);
        if (!tokens.every((token) => title.includes(token))) continue;
        matches.add(node.id);
        let ancestor = node;
        while (ancestor) {
          keep.add(ancestor.id);
          ancestor = byId.get(ancestor.parentId);
        }
      }
    }
    const result = [];
    const visit = (nodes) => {
      for (const node of nodes) {
        if (tokens.length && !keep.has(node.id)) continue;
        const expanded = tokens.length > 0 || !this.current.collapsed.has(node.id);
        result.push({ ...node, expanded, match: matches.has(node.id) });
        if (expanded) visit(node.children);
      }
    };
    visit(this.current.roots);
    return result;
  }

  visibleActiveNode() {
    let active = this.activeNode();
    if (!active) return null;
    const visible = new Set(this.visibleNodes().map((node) => node.id));
    const byId = new Map(this.current.flat.map((node) => [node.id, node]));
    while (active && !visible.has(active.id)) active = byId.get(active.parentId);
    return active || null;
  }
}

/** A lightweight DOM controller; labels belong to the application's i18n. */
export function createOutlineNavigator({ container, onNavigate, labels = {}, follow = false, documentLimit } = {}) {
  if (!container) throw new TypeError("Outline container is required");
  const documentRef = container.ownerDocument;
  const model = new OutlineNavigatorModel({ documentLimit });
  let text = { empty: "No headings yet.", noMatches: "No matching headings.", expand: "Expand section", collapse: "Collapse section", label: "Document outline", ...labels };
  let following = Boolean(follow);
  let lastManualNavigation = 0;
  let focusedId = null;
  let paintedActiveId;
  let buttons = new Map();
  let rows = [];

  container.classList.add("outline-navigator");
  container.setAttribute("role", "tree");
  container.setAttribute("aria-label", text.label);

  function focusNode(id) {
    const target = buttons.get(id);
    if (!target) return;
    for (const button of buttons.values()) button.tabIndex = button === target ? 0 : -1;
    focusedId = id;
    target.focus({ preventScroll: true });
    target.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }

  function markActive({ scroll = false, force = false } = {}) {
    const active = model.activeNode();
    if (!force && paintedActiveId === (active?.id || null)) return;
    paintedActiveId = active?.id || null;
    const visibleActive = model.visibleActiveNode();
    for (const [id, button] of buttons) {
      button.classList.toggle("active", id === active?.id);
      button.classList.toggle("outline-branch-current", id === visibleActive?.id && id !== active?.id);
      if (id === active?.id) button.setAttribute("aria-current", "location");
      else button.removeAttribute("aria-current");
    }
    if (scroll && following && Date.now() - lastManualNavigation > 3000 && container.getClientRects().length) {
      buttons.get(visibleActive?.id)?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    }
  }

  function render() {
    const hadFocus = container.contains(documentRef.activeElement);
    const previousFocusedId = focusedId;
    buttons = new Map();
    rows = model.visibleNodes();
    container.setAttribute("role", rows.length ? "tree" : "region");
    const fragment = documentRef.createDocumentFragment();
    const active = model.visibleActiveNode();
    const tabId = rows.some((node) => node.id === focusedId) ? focusedId : active?.id || rows[0]?.id;
    const siblingCounts = new Map();
    const siblingPositions = new Map();
    for (const node of rows) siblingCounts.set(node.parentId, (siblingCounts.get(node.parentId) || 0) + 1);
    container.dataset.filtered = String(Boolean(model.query.trim()));
    if (!rows.length) {
      const empty = documentRef.createElement("p");
      empty.className = "tool-empty outline-empty";
      empty.setAttribute("role", "status");
      empty.textContent = model.query.trim() ? text.noMatches : text.empty;
      fragment.append(empty);
    }
    for (const node of rows) {
      const row = documentRef.createElement("div");
      row.className = "outline-row";
      row.setAttribute("role", "none");
      row.style.setProperty("--outline-depth", String(node.depth));
      // The heading is the sole accessible treeitem. Its arrow-key contract
      // provides expansion to keyboard and assistive-technology users; this
      // pointer hit area avoids inserting unrelated buttons into the tree.
      const disclosure = documentRef.createElement("span");
      disclosure.className = "outline-disclosure";
      disclosure.setAttribute("aria-hidden", "true");
      if (node.children.length) {
        disclosure.title = `${node.expanded ? text.collapse : text.expand}: ${node.title}`;
        disclosure.dataset.expanded = String(node.expanded);
        const chevron = documentRef.createElement("span");
        chevron.setAttribute("aria-hidden", "true");
        chevron.className = "outline-chevron";
        chevron.textContent = "›";
        disclosure.append(chevron);
        disclosure.addEventListener("click", () => {
          lastManualNavigation = Date.now();
          model.toggle(node.id);
          focusedId = node.id;
          render();
          focusNode(node.id);
        });
      } else {
        disclosure.dataset.leaf = "true";
      }
      const button = documentRef.createElement("button");
      button.type = "button";
      button.className = "outline-heading";
      button.setAttribute("role", "treeitem");
      button.setAttribute("aria-level", String(node.depth + 1));
      if (node.children.length) button.setAttribute("aria-expanded", String(node.expanded));
      const siblingPosition = (siblingPositions.get(node.parentId) || 0) + 1;
      siblingPositions.set(node.parentId, siblingPosition);
      button.setAttribute("aria-posinset", String(siblingPosition));
      button.setAttribute("aria-setsize", String(siblingCounts.get(node.parentId)));
      button.dataset.sourceLine = String(node.line);
      button.dataset.level = String(node.level);
      button.dataset.outlineId = node.id;
      button.tabIndex = node.id === tabId ? 0 : -1;
      button.title = node.title;
      const title = documentRef.createElement("span");
      title.className = "outline-heading-title";
      title.dir = "auto";
      title.textContent = node.title;
      button.append(title);
      button.addEventListener("focus", () => {
        focusedId = node.id;
        for (const item of buttons.values()) item.tabIndex = item === button ? 0 : -1;
      });
      button.addEventListener("click", () => {
        focusedId = node.id;
        lastManualNavigation = Date.now();
        onNavigate?.(node.line, node);
      });
      row.append(disclosure, button);
      fragment.append(row);
      buttons.set(node.id, button);
    }
    container.replaceChildren(fragment);
    markActive({ force: true });
    if (hadFocus) focusNode(buttons.has(previousFocusedId) ? previousFocusedId : tabId);
  }

  function onKeyDown(event) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target.closest?.(".outline-heading");
    if (!target || !container.contains(target)) return;
    const index = rows.findIndex((node) => node.id === target.dataset.outlineId);
    const node = rows[index];
    if (!node) return;
    const rtl = documentRef.defaultView?.getComputedStyle(container).direction === "rtl";
    const expandKey = rtl ? "ArrowLeft" : "ArrowRight";
    const collapseKey = rtl ? "ArrowRight" : "ArrowLeft";
    let destination = null;
    if (event.key === "ArrowDown") destination = rows[Math.min(rows.length - 1, index + 1)];
    else if (event.key === "ArrowUp") destination = rows[Math.max(0, index - 1)];
    else if (event.key === "Home") destination = rows[0];
    else if (event.key === "End") destination = rows.at(-1);
    else if (event.key === expandKey) {
      if (node.children.length && !node.expanded) {
        model.toggle(node.id, true);
        render();
        destination = node;
      } else if (node.children.length) destination = rows[index + 1];
    } else if (event.key === collapseKey) {
      if (node.children.length && node.expanded && !model.query.trim()) {
        model.toggle(node.id, false);
        render();
        destination = node;
      } else destination = rows.find((entry) => entry.id === node.parentId);
    } else return;
    event.preventDefault();
    lastManualNavigation = Date.now();
    if (destination) focusNode(destination.id);
  }

  function pauseFollow() { lastManualNavigation = Date.now(); }
  container.addEventListener("keydown", onKeyDown);
  container.addEventListener("wheel", pauseFollow, { passive: true });

  return {
    setItems(items, { documentId = "document" } = {}) {
      const switchingDocument = String(documentId) !== model.documentId;
      if (model.setDocument(documentId, items)) {
        if (switchingDocument) focusedId = null;
        render();
        return true;
      }
      return false;
    },
    setActiveLine(line, options) { model.setActiveLine(line); markActive(options); },
    setFilter(query) { if (model.setQuery(query)) render(); },
    setFollow(enabled) {
      following = Boolean(enabled);
      if (following) {
        lastManualNavigation = 0;
        markActive({ scroll: true, force: true });
      }
    },
    setLabels(next) { text = { ...text, ...next }; container.setAttribute("aria-label", text.label); render(); },
    expandAll() { model.expandAll(); render(); },
    collapseAll() { model.collapseAll(); render(); },
    forgetDocument(id) { model.forgetDocument(id); },
    get count() { return model.current.flat.length; },
    get activeLine() { return model.activeNode()?.line || null; },
    focus() { focusNode(focusedId || model.visibleActiveNode()?.id || rows[0]?.id); },
    destroy() {
      container.removeEventListener("keydown", onKeyDown);
      container.removeEventListener("wheel", pauseFollow);
      container.replaceChildren();
    },
  };
}
