import { syntaxTree } from "@codemirror/language";
import { EditorSelection, Transaction } from "@codemirror/state";
import { ViewPlugin } from "@codemirror/view";
import { isolateHistory } from "@codemirror/commands";
import { spriteIcon } from "../frontend/js/ui/icons.mjs";

const headingLevel = (node) => Number(/^(?:ATX|Setext)Heading([1-6])$/.exec(node.name)?.[1]);

export function movableBlock(state, position, listItem = true, includeSection = true) {
  const tree = syntaxTree(state);
  let node = tree.resolveInner(position, 1);
  if (node.name === "Document") node = tree.resolveInner(position, -1);
  while (node.parent) {
    if (node.name === "ListItem" && listItem) break;
    if (node.parent.name === "Document") break;
    node = node.parent;
  }
  if (!node.parent || ["Frontmatter", "LinkReference"].includes(node.name)) return null;
  const parent = node.parent;
  const level = headingLevel(node);
  let last = node;
  if (level && includeSection) {
    while (last.nextSibling && !(headingLevel(last.nextSibling) <= level)) last = last.nextSibling;
  }
  return {
    from: state.doc.lineAt(node.from).from,
    to: state.doc.lineAt(last.to).to,
    scope: parent.from + ":" + parent.to,
    item: node.name === "ListItem",
    section: Boolean(level),
  };
}

function dropBoundary(view, target, after) {
  const doc = view.state.doc;
  const edge = doc.lineAt(after ? target.to : target.from).number;
  let previous = after ? edge : edge - 1;
  let next = after ? edge + 1 : edge;
  while (previous >= 1 && !doc.line(previous).text.trim()) previous -= 1;
  while (next <= doc.lines && !doc.line(next).text.trim()) next += 1;
  const bottom = previous > 0 ? view.lineBlockAt(doc.line(previous).to).bottom : null;
  const top = next <= doc.lines ? view.lineBlockAt(doc.line(next).from).top : null;
  if (bottom == null) return top;
  if (top == null) return bottom;
  return (bottom + top) / 2;
}

let previewSequence = 0;

/** Preserve rendered markup without giving the preview live controls or duplicate SVG IDs. */
function copyBlockAppearance(element, namespace) {
  const copy = element.cloneNode(true);
  const ids = new Map();
  for (const item of [copy, ...copy.querySelectorAll("[id]")]) {
    if (!item.id) continue;
    const next = namespace + item.id;
    ids.set(item.id, next);
    item.id = next;
  }
  for (const item of copy.querySelectorAll("*")) {
    for (const attribute of item.attributes) {
      if (!attribute.value.includes("#")) continue;
      const value = attribute.value
        .replace(/^#(.+)$/, (original, id) => (ids.has(id) ? "#" + ids.get(id) : original))
        .replace(/url\(#([^)]+)\)/g, (original, id) =>
          ids.has(id) ? "url(#" + ids.get(id) + ")" : original,
        );
      if (value !== attribute.value) attribute.value = value;
    }
  }
  for (const popup of copy.querySelectorAll("[popover]")) popup.remove();
  const originals = element.querySelectorAll("input, textarea, select");
  copy.querySelectorAll("input, textarea, select").forEach((control, index) => {
    control.value = originals[index]?.value ?? "";
    if (control.type === "checkbox") control.checked = originals[index]?.checked ?? false;
  });
  return copy;
}

/** Swap whole source lines and retain all intervening Markdown and whitespace. */
export function blockMove(state, source, target, after) {
  if (!source || !target || source.scope !== target.scope) return null;
  if (source.from <= target.to && target.from <= source.to) return null;
  const slice = (from, to) => state.doc.sliceString(from, to);
  const moving = slice(source.from, source.to);
  const down = source.from < target.from;
  const tail = target[after ? "to" : "from"];

  if (down) {
    const gap = /^\n(?:[ \t]*\n)*/.exec(slice(source.to, target.from))?.[0];
    if (!gap) return null;
    const middle = slice(source.to + gap.length, tail);
    if (!middle) return null;
    return {
      from: source.from,
      to: tail,
      insert: after ? middle + gap + moving : middle + moving + gap,
    };
  }
  const gap = /\n(?:[ \t]*\n)*$/.exec(slice(target.to, source.from))?.[0];
  if (!gap) return null;
  const middle = slice(tail, source.from - gap.length);
  if (!middle) return null;
  return {
    from: tail,
    to: source.to,
    insert: after ? gap + moving + middle : moving + gap + middle,
  };
}

export const blockDragExtension = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.view = view;
      this.grip = document.createElement("button");
      this.grip.type = "button";
      this.grip.className = "cm-block-grip";
      this.grip.append(spriteIcon("grip"));
      const fa = document.documentElement.lang.startsWith("fa");
      this.grip.ariaLabel = fa ? "انتخاب یا جابه‌جایی بلوک" : "Select or move document block";
      this.grip.title = fa
        ? "کلیک برای انتخاب، کشیدن برای جابه‌جایی"
        : "Click to select, drag to move";
      this.grip.setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown");
      this.indicator = document.createElement("div");
      this.indicator.className = "cm-block-drop";
      this.indicator.setAttribute("aria-hidden", "true");
      this.ghost = document.createElement("div");
      this.ghost.className = "cm-block-drag-ghost";
      this.ghost.setAttribute("aria-hidden", "true");
      this.ghost.inert = true;
      this.origin = new Set();
      this.grip.hidden = this.indicator.hidden = this.ghost.hidden = true;
      view.dom.append(this.grip, this.indicator, this.ghost);
      const hide = () => {
        this.grip.hidden = true;
        this.targetTable?.classList.remove("cm-block-hover");
        this.targetTable = null;
      };
      this.hide = hide;
      const find = (event) => {
        if (event.target?.closest?.(".cm-block-grip, .cm-table-actions")) return;
        this.hoverPoint = { clientX: event.clientX, clientY: event.clientY };
        const bounds = view.dom.getBoundingClientRect();
        const column = view.contentDOM.getBoundingClientRect();
        const padding = getComputedStyle(view.contentDOM);
        const left = column.left + parseFloat(padding.paddingLeft);
        const right = column.right - parseFloat(padding.paddingRight);
        const widget = event.target?.closest?.(
          "[data-table-from], [data-diagram-from], .cm-md-rule, .cm-md-math-block-preview, .cm-document-disclosure",
        );
        const targetLine = event.target?.closest?.(".cm-line");
        if (!this.grab && !widget && (!targetLine || !targetLine.textContent.trim())) {
          if (!this.grip.hidden) {
            const anchor = this.grip.getBoundingClientRect();
            const x = event.clientX,
              y = event.clientY;
            if (
              x >= anchor.left - 6 &&
              x <= anchor.right + 6 &&
              y >= anchor.top &&
              y <= anchor.bottom + (this.targetTable ? 26 : 3)
            )
              return;
          }
          hide();
          return;
        }
        const position = widget
          ? Number(widget.dataset.tableFrom ?? widget.dataset.diagramFrom ?? view.posAtDOM(widget))
          : targetLine
            ? Math.min(view.state.doc.length, view.posAtDOM(targetLine) + 1)
            : view.posAtCoords({ x: event.clientX, y: event.clientY }, false);
        if (position == null) {
          this.drop = null;
          this.indicator.hidden = true;
          return;
        }
        const block = this.grab
          ? movableBlock(view.state, position, this.grab.item, this.grab.section)
          : movableBlock(view.state, position);
        const line = view.lineBlockAt(position);
        const top = view.documentTop + line.top;
        if (this.grab) {
          if (this.ghost.hidden) return;
          const hit = (targetLine || widget)?.getBoundingClientRect();
          const after = event.clientY > (hit ? hit.top + hit.height / 2 : top + line.height / 2);
          this.drop = blockMove(view.state, this.grab, block, after);
          this.indicator.hidden = !this.drop;
          if (this.drop) {
            const directionAnchor = widget || targetLine || view.contentDOM;
            this.indicator.dir = getComputedStyle(directionAnchor).direction;
            this.indicator.style.left = Math.max(0, left - bounds.left) + "px";
            this.indicator.style.width = Math.max(0, right - left) + "px";
            this.indicator.style.top =
              view.documentTop + dropBoundary(view, block, after) - bounds.top + "px";
          }
        } else if (block && !view.state.readOnly) {
          this.source = block;
          const first = view.lineBlockAt(block.from);
          const at = view.domAtPos(Math.min(view.state.doc.length, block.from + 1)).node;
          const firstLine = (at.nodeType === 1 ? at : at.parentElement)?.closest(".cm-line");
          const fold = firstLine?.querySelector(".cm-section-toggle");
          const table = widget?.matches("[data-table-from]") ? widget : null;
          const actualBlock =
            table?.querySelector("table") || widget?.querySelector("header") || widget || firstLine;
          const rect = (fold || actualBlock)?.getBoundingClientRect();
          const gripHeight = 23;
          const anchorY = rect
            ? rect.top + (table ? 6 : Math.min(rect.height, 30) / 2 - gripHeight / 2)
            : view.documentTop + first.top + Math.min(first.height, 30) / 2 - gripHeight / 2;
          const viewport = view.scrollDOM.getBoundingClientRect();
          if (anchorY < viewport.top || anchorY + gripHeight > viewport.bottom) {
            hide();
            return;
          }
          if (this.targetTable !== table) {
            this.targetTable?.classList.remove("cm-block-hover");
            this.targetTable = table;
            table?.classList.add("cm-block-hover");
          }
          this.grip.style.top = anchorY - bounds.top + "px";
          const directionAnchor = table || firstLine || widget;
          const rtl = directionAnchor && getComputedStyle(directionAnchor).direction === "rtl";
          const gripX = rtl
            ? (rect?.right ?? right) + 5 - bounds.left
            : (rect?.left ?? left) - bounds.left - 26;
          this.grip.style.left = Math.max(4, Math.min(gripX, bounds.width - 25)) + "px";
          this.grip.dir = rtl ? "rtl" : "ltr";
          this.grip.hidden = false;
        } else hide();
      };
      this.hover = find;
      this.leave = () => {
        if (!this.grab) {
          this.hoverPoint = null;
          if (document.activeElement !== this.grip) hide();
        }
      };
      this.reposition = () => {
        if (this.grab) return;
        hide();
        const point = this.hoverPoint;
        if (!point) return;
        const target = document.elementFromPoint(point.clientX, point.clientY);
        if (view.contentDOM.contains(target)) find({ ...point, target });
      };
      this.onScroll = () => {
        if (this.scrollFrame) return;
        this.scrollFrame = requestAnimationFrame(() => {
          this.scrollFrame = 0;
          this.reposition();
        });
      };
      view.scrollDOM.addEventListener("scroll", this.onScroll, { passive: true });
      view.dom.addEventListener("pointermove", find);
      view.dom.addEventListener("pointerleave", this.leave);
      this.grip.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || !this.source || view.state.readOnly) return;
        event.preventDefault();
        this.grab = this.source;
        this.start = { x: event.clientX, y: event.clientY };
        this.pointer = event.pointerId;
        this.grip.setPointerCapture(event.pointerId);
        const scroll = () => {
          if (!this.grab) return;
          const point = this.point;
          if (point) {
            const scrollbox = view.scrollDOM.getBoundingClientRect();
            const { clientX, clientY } = point;
            if (clientX >= scrollbox.left && clientX <= scrollbox.right) {
              const offset =
                clientY < scrollbox.top + 30
                  ? (clientY - scrollbox.top - 30) / 3
                  : Math.max(0, (clientY - scrollbox.bottom + 30) / 3);
              if (offset) {
                const before = view.scrollDOM.scrollTop;
                view.scrollDOM.scrollTop += Math.max(-18, Math.min(18, offset));
                if (view.scrollDOM.scrollTop !== before) {
                  const y = Math.max(scrollbox.top + 1, Math.min(clientY, scrollbox.bottom - 1));
                  find({ clientX, clientY: y, target: document.elementFromPoint(clientX, y) });
                }
              }
            }
          }
          requestAnimationFrame(scroll);
        };
        requestAnimationFrame(scroll);
      });
      this.grip.addEventListener("pointermove", (event) => {
        if (this.grab) {
          if (this.ghost.hidden) {
            const distance = Math.hypot(event.clientX - this.start.x, event.clientY - this.start.y);
            if (distance < 5) return;
            this.liftBlock();
          }
          const width = this.ghost.offsetWidth;
          const height = this.ghost.offsetHeight;
          const left = this.grip.dir === "rtl" ? event.clientX - width - 14 : event.clientX + 14;
          this.ghost.style.left = Math.max(8, Math.min(left, innerWidth - width - 8)) + "px";
          this.ghost.style.top =
            Math.max(8, Math.min(event.clientY + 12, innerHeight - height - 8)) + "px";
          this.point = event;
          find({
            clientX: event.clientX,
            clientY: event.clientY,
            target: document.elementFromPoint(event.clientX, event.clientY),
          });
        }
      });
      const finish = (event) => {
        if (event.type === "pointerup") {
          if (this.drop) this.move(this.drop);
          else if (this.grab && this.ghost.hidden) this.select(this.grab, event.shiftKey);
        }
        this.endDrag();
      };
      this.grip.addEventListener("pointerup", finish);
      this.grip.addEventListener("pointercancel", finish);
      this.grip.addEventListener("lostpointercapture", finish);
      this.cancelKey = (event) => {
        if (event.key !== "Escape" || !this.grab) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        this.endDrag();
      };
      view.dom.ownerDocument.addEventListener("keydown", this.cancelKey, true);
      this.grip.addEventListener("keydown", (event) => {
        if (this.source && ["Enter", " "].includes(event.key)) {
          event.preventDefault();
          this.select(this.source, event.shiftKey);
          return;
        }
        if (!this.source || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
        const down = event.key === "ArrowDown";
        const doc = view.state.doc;
        let line = doc.lineAt(this.source[down ? "to" : "from"]).number + (down ? 1 : -1);
        while (line >= 1 && line <= doc.lines && !doc.line(line).text.trim()) line += down ? 1 : -1;
        if (line < 1 || line > doc.lines) return;
        event.preventDefault();
        const targetLine = doc.line(line);
        const target = movableBlock(
          view.state,
          targetLine.from + (targetLine.text.search(/\S/) || 0),
          this.source.item,
          this.source.section,
        );
        this.move(blockMove(view.state, this.source, target, down));
      });
    }

    select(block, extend) {
      const { view } = this;
      if (view.state.readOnly) return;
      const current = view.state.selection.main;
      const selection =
        extend && !current.empty
          ? EditorSelection.range(
              Math.min(block.from, current.from),
              Math.max(block.to, current.to),
            )
          : EditorSelection.range(block.from, block.to);
      view.dispatch({ selection, userEvent: "select.block" });
      view.focus();
    }

    updateWidgetSelection() {
      const view = this.view;
      view.requestMeasure({
        read: () =>
          Array.from(view.contentDOM.children)
            .filter((element) =>
              element.matches(
                ".cm-md-table, .cm-diagram, .cm-md-math-block-preview, .cm-md-rule, .cm-document-disclosure, .cm-md-frontmatter",
              ),
            )
            .map((element) => {
              const from = view.posAtDOM(element, 0);
              const position = Math.min(view.state.doc.length, from + 1);
              const range = movableBlock(view.state, position, false, false);
              const selected =
                range &&
                view.state.selection.ranges.some(
                  (selection) =>
                    !selection.empty && selection.from <= range.from && selection.to >= range.to,
                );
              return [element, Boolean(selected)];
            }),
        write: (items) => {
          for (const [element, selected] of items)
            element.classList.toggle("cm-document-selected-block", selected);
        },
        key: this.updateWidgetSelection,
      });
    }

    liftBlock() {
      const { view } = this;
      const material = document.createElement("div");
      material.className = "cm-block-drag-copy";
      const namespace = "drag-" + ++previewSequence + "-";
      for (const element of view.contentDOM.children) {
        if (element.classList.contains("cm-gap")) continue;
        const position = view.posAtDOM(element);
        if (position < this.grab.from || position > this.grab.to) continue;
        material.append(copyBlockAppearance(element, namespace));
        element.classList.add("cm-block-drag-origin");
        this.origin.add(element);
      }
      const style = getComputedStyle(view.contentDOM);

      material.dir = style.direction;
      const width =
        view.contentDOM.clientWidth -
        parseFloat(style.paddingLeft) -
        parseFloat(style.paddingRight);
      material.style.inlineSize = Math.max(1, width) + "px";
      this.ghost.replaceChildren(material);
      this.ghost.hidden = false;
      const height = material.offsetHeight;
      material.style.zoom = Math.min(
        1,
        (innerWidth - 36) / Math.max(1, width),
        (innerHeight * 0.62) / Math.max(1, height),
      );
      const scrollable = ".cm-table-scroll, .cm-code-nowrap";
      const scrolls = [...this.origin].flatMap((element) => [
        ...(element.matches(scrollable) ? [element] : []),
        ...element.querySelectorAll(scrollable),
      ]);
      material.querySelectorAll(scrollable).forEach((element, index) => {
        element.scrollLeft = scrolls[index]?.scrollLeft || 0;
      });
    }

    endDrag() {
      const pointer = this.pointer;
      this.point = this.drop = this.grab = this.pointer = null;
      this.indicator.hidden = this.ghost.hidden = true;
      this.ghost.replaceChildren();
      this.origin.forEach((element) => element.classList.remove("cm-block-drag-origin"));
      this.origin.clear();
      if (pointer != null && this.grip.hasPointerCapture(pointer))
        this.grip.releasePointerCapture(pointer);
    }

    move(change) {
      if (!change || this.view.state.readOnly) return;
      this.view.dispatch({
        changes: change,
        annotations: [Transaction.userEvent.of("move.drop"), isolateHistory.of("full")],
      });
      this.hide();
      this.view.focus();
    }

    update(update) {
      const hasSelection = (state) => state.selection.ranges.some((range) => !range.empty);
      if (
        (update.selectionSet || update.viewportChanged || update.docChanged) &&
        (hasSelection(update.state) || hasSelection(update.startState))
      )
        this.updateWidgetSelection();
      if (update.docChanged) {
        this.endDrag();
        this.source = null;
        this.hide();
        this.indicator.hidden = true;
      } else if (update.geometryChanged && !this.grip.hidden) {
        this.view.requestMeasure({ read: () => null, write: this.reposition, key: this });
      }
    }

    destroy() {
      this.view.scrollDOM.removeEventListener("scroll", this.onScroll);
      if (this.scrollFrame) cancelAnimationFrame(this.scrollFrame);
      this.view.dom.removeEventListener("pointermove", this.hover);
      this.view.dom.removeEventListener("pointerleave", this.leave);
      this.view.dom.ownerDocument.removeEventListener("keydown", this.cancelKey, true);
      this.endDrag();
      this.hide();
      this.grip.remove();
      this.indicator.remove();
      this.ghost.remove();
    }
  },
);
