import { syntaxTree } from "@codemirror/language";
import { Transaction } from "@codemirror/state";
import { ViewPlugin } from "@codemirror/view";
import { isolateHistory } from "@codemirror/commands";

const headingLevel = (node) => Number(/^(?:ATX|Setext)Heading([1-6])$/.exec(node.name)?.[1]);

export function movableBlock(state, position, listItem = true) {
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
  if (level) {
    while (last.nextSibling && !(headingLevel(last.nextSibling) <= level)) last = last.nextSibling;
  }
  return {
    from: state.doc.lineAt(node.from).from,
    to: state.doc.lineAt(last.to).to,
    scope: parent.from + ":" + parent.to,
    item: node.name === "ListItem",
  };
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
      this.grip.textContent = "⠿";
      const fa = document.documentElement.lang.startsWith("fa");
      this.grip.title = this.grip.ariaLabel = fa ? "جابجایی بلوک سند" : "Move document block";
      this.grip.setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown");
      this.indicator = document.createElement("div");
      this.indicator.className = "cm-block-drop";
      this.indicator.setAttribute("aria-hidden", "true");
      this.grip.hidden = this.indicator.hidden = true;
      view.dom.append(this.grip, this.indicator);
      const find = (event) => {
        if (event.target?.closest?.(".cm-block-grip, .cm-table-selection-handle")) return;
        const bounds = view.dom.getBoundingClientRect();
        const column = view.contentDOM.getBoundingClientRect();
        const padding = getComputedStyle(view.contentDOM);
        const left = column.left + parseFloat(padding.paddingLeft);
        const right = column.right - parseFloat(padding.paddingRight);
        const widget = event.target?.closest?.("[data-table-from], [data-diagram-from]");
        const targetLine = event.target?.closest?.(".cm-line");
        const position = widget
          ? Number(widget.dataset.tableFrom ?? widget.dataset.diagramFrom)
          : targetLine
            ? Math.min(view.state.doc.length, view.posAtDOM(targetLine) + 1)
            : view.posAtCoords({ x: event.clientX, y: event.clientY }, false);
        if (position == null) {
          this.drop = null;
          this.indicator.hidden = true;
          return;
        }
        const block = this.grab
          ? movableBlock(view.state, position, this.grab.item)
          : movableBlock(view.state, position);
        const line = view.lineBlockAt(position);
        const top = view.documentTop + line.top;
        if (this.grab) {
          const after = event.clientY > top + line.height / 2;
          this.drop = blockMove(view.state, this.grab, block, after);
          this.indicator.hidden = !this.drop;
          if (this.drop) {
            this.indicator.style.left = Math.max(0, left - bounds.left) + "px";
            this.indicator.style.width = Math.max(0, right - left) + "px";
            const edge = view.lineBlockAt(after ? block.to : block.from);
            this.indicator.style.top =
              view.documentTop +
              (after ? edge.bottom : edge.top) -
              view.dom.getBoundingClientRect().top +
              "px";
          }
        } else if (block && !view.state.readOnly) {
          this.source = block;
          const first = view.lineBlockAt(block.from);
          this.grip.style.top =
            view.documentTop + first.top - view.dom.getBoundingClientRect().top + "px";
          this.grip.style.left = Math.max(4, left - bounds.left - 26) + "px";
          this.grip.hidden = false;
        } else this.grip.hidden = true;
      };
      this.hover = find;
      this.leave = () => {
        if (!this.grab && document.activeElement !== this.grip) this.grip.hidden = true;
      };
      view.dom.addEventListener("pointermove", find);
      view.dom.addEventListener("pointerleave", this.leave);
      this.grip.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || !this.source || view.state.readOnly) return;
        event.preventDefault();
        this.grab = this.source;
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
          this.point = event;
          find({
            clientX: event.clientX,
            clientY: event.clientY,
            target: document.elementFromPoint(event.clientX, event.clientY),
          });
        }
      });
      const finish = (event) => {
        if (event.type === "pointerup" && this.drop) this.move(this.drop);
        this.point = this.drop = this.grab = null;
        this.indicator.hidden = true;
      };
      this.grip.addEventListener("pointerup", finish);
      this.grip.addEventListener("pointercancel", finish);
      this.grip.addEventListener("lostpointercapture", finish);
      this.grip.addEventListener("keydown", (event) => {
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
        );
        this.move(blockMove(view.state, this.source, target, down));
      });
    }

    move(change) {
      if (!change || this.view.state.readOnly) return;
      this.view.dispatch({
        changes: change,
        annotations: [Transaction.userEvent.of("move.drop"), isolateHistory.of("full")],
      });
      this.grip.hidden = true;
      this.view.focus();
    }

    update(update) {
      if (!update.docChanged) return;
      this.source = this.grab = this.drop = null;
      this.grip.hidden = this.indicator.hidden = true;
    }

    destroy() {
      this.view.dom.removeEventListener("pointermove", this.hover);
      this.view.dom.removeEventListener("pointerleave", this.leave);
      this.grip.remove();
      this.indicator.remove();
    }
  },
);
