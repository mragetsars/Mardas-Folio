import { Facet, Transaction } from "@codemirror/state";
import { WidgetType } from "@codemirror/view";
import { isolateHistory } from "@codemirror/commands";
import { codeBodyText } from "./code-block-tools.mjs";
import { spriteIcon } from "../frontend/js/ui/icons.mjs";

export const diagramRenderer = Facet.define({ combine: (values) => values[0] || null });
const measuredDiagramHeights = new Map();

const shapes = {
  subroutine: ["[[", "]]", "Subroutine", "زیرفرایند"],
  hexagon: ["{{", "}}", "Hexagon", "شش‌ضلعی"],
  circle: ["((", "))", "Circle", "دایره"],
  database: ["[(", ")]", "Database", "پایگاه داده"],
  stadium: ["([", "])", "Stadium", "کپسولی"],
  parallelogram: ["[/", "/]", "Parallelogram", "متوازی‌الاضلاع"],
  reverseParallelogram: ["[\\", "\\]", "Reverse parallelogram", "متوازی‌الاضلاع معکوس"],
  rect: ["[", "]", "Rectangle", "مستطیل"],
  round: ["(", ")", "Rounded", "گوشه‌گرد"],
  diamond: ["{", "}", "Diamond", "لوزی"],
};

function readNode(source) {
  const match = /^([A-Za-z_](?:[\w]|[.-](?![.->]))*)/.exec(source.trimStart());
  if (
    !match ||
    /^(?:classDef|class|style|click|direction|end|subgraph|linkStyle|accTitle|accDescr)$/i.test(
      match[1],
    )
  )
    return null;
  const id = match[1];
  const rest = source.trimStart().slice(id.length).trimStart();
  for (const [shape, [opening, closing]] of Object.entries(shapes)) {
    if (!rest.startsWith(opening)) continue;
    const end = rest.indexOf(closing, opening.length);
    if (end < 0) return null;
    const value = rest.slice(opening.length, end).trim();
    const label = value.replace(/^(["'])([\s\S]*)\1$/, "$2");
    if (!label || /[";\r\n]|%%/.test(label)) return null;
    return {
      node: { id, label, shape },
      rest: rest.slice(end + closing.length).trimStart(),
      defined: true,
    };
  }
  return { node: { id, label: id, shape: "rect" }, rest, defined: false };
}

function readEdge(source) {
  const plain = /^(-->|---|-\.->|==>)\s*(?:\|([^|]+)\|\s*)?/.exec(source);
  if (plain && !(plain[1] === "---" && plain[2])) {
    return { kind: plain[1], label: (plain[2] || "").trim(), rest: source.slice(plain[0].length) };
  }
  const solid = /^--\s*([^-]+?)\s*-->\s*/.exec(source);
  const dotted = /^-\.\s*([^.]+?)\s*\.->\s*/.exec(source);
  const labeled = solid || dotted;
  return labeled
    ? {
        kind: solid ? "-->" : "-.->",
        label: labeled[1].trim(),
        rest: source.slice(labeled[0].length),
      }
    : null;
}

/** Only offer editing when every statement can be represented by the form. */
export function diagramModel(source) {
  const lines = source
    .trim()
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const header = /^(graph|flowchart)\s+(TD|TB|LR|RL|BT)$/i.exec(lines.shift() || "");
  if (!header) return null;
  const nodes = new Map();
  const edges = [];
  const add = (part) => {
    if (part.defined || !nodes.has(part.node.id)) nodes.set(part.node.id, part.node);
  };
  for (const line of lines) {
    let current = readNode(line);
    if (!current) return null;
    add(current);
    while (current.rest) {
      const edge = readEdge(current.rest);
      const next = edge && readNode(edge.rest);
      if (!next) return null;
      edges.push({ from: current.node.id, to: next.node.id, kind: edge.kind, label: edge.label });
      add(next);
      current = next;
    }
  }
  return {
    declaration: header[1],
    direction: header[2].toUpperCase(),
    nodes: [...nodes.values()],
    edges,
  };
}

export function diagramSource(model) {
  const nodes = model.nodes.map(({ id, label, shape }) => {
    const [left, right] = shapes[shape];
    return "  " + id + left + '"' + (label.trim() || id) + '"' + right;
  });
  const edges = model.edges.map(
    ({ from, to, kind, label }) =>
      "  " +
      from +
      " " +
      kind +
      (kind !== "---" && label.trim() ? "|" + label.trim() + "|" : "") +
      " " +
      to,
  );
  return [(model.declaration || "flowchart") + " " + model.direction, ...nodes, ...edges].join(
    "\n",
  );
}

export class DiagramWidget extends WidgetType {
  constructor(source, spec, renderer, readOnly) {
    super();
    this.source = source;
    this.spec = spec;
    this.renderer = renderer;
    this.readOnly = readOnly;
    this.initialModel = diagramModel(source);
  }

  eq(other) {
    return (
      this.source === other.source &&
      this.spec.openerFrom === other.spec.openerFrom &&
      this.renderer === other.renderer &&
      this.readOnly === other.readOnly
    );
  }

  get estimatedHeight() {
    return (
      measuredDiagramHeights.get(this.source) ??
      Math.max(140, Math.min(540, 100 + (this.initialModel?.nodes.length || 2) * 24))
    );
  }
  ignoreEvent() {
    return true;
  }

  toDOM(view) {
    const fa = document.documentElement.lang.startsWith("fa");
    const t = (en, persian) => (fa ? persian : en);
    const widget = document.createElement("section");
    widget.className = "cm-diagram";
    widget.dataset.diagramFrom = this.spec.from;
    const header = document.createElement("header");
    header.textContent = t("Mermaid diagram", "نمودار Mermaid");
    const canvas = document.createElement("div");
    canvas.className = "cm-diagram-canvas";
    canvas.textContent = t("Rendering diagram…", "در حال نمایش نمودار…");
    canvas.style.minBlockSize = Math.max(100, this.estimatedHeight - 75) + "px";
    let model = this.initialModel ? structuredClone(this.initialModel) : null;
    let previewRevision = 0;
    let previewTimer;
    let selection = null;
    let connecting = false;
    let startNode = null;
    const reflectCanvas = () => {
      for (const item of canvas.querySelectorAll("[data-diagram-pick]")) {
        const kind = item.dataset.diagramPick;
        const index = Number(item.dataset.diagramIndex);
        item.setAttribute(
          "aria-pressed",
          String(
            (selection?.kind === kind && selection.index === index) ||
              (kind === "nodes" && model.nodes[index]?.id === startNode),
          ),
        );
      }
    };
    const render = async (source = this.source) => {
      const revision = ++previewRevision;
      try {
        const svg = await this.renderer?.(source);
        if (revision !== previewRevision) return;
        if (svg) {
          const previous = document.activeElement?.closest?.("[data-diagram-pick]");
          const focusKey = previous && canvas.contains(previous) ? previous.dataset : null;
          canvas.replaceChildren(svg);
          canvas.style.minBlockSize = "";
          if (model && !this.readOnly) {
            svg.setAttribute("role", "group");
            for (const [kind, selector] of [
              ["nodes", ".md2pdf-mermaid-node[data-node-id]"],
              ["edges", ".md2pdf-mermaid-edge"],
            ]) {
              const elements = Array.from(svg.querySelectorAll(selector));
              if (kind === "edges" && elements.length !== model.edges.length) continue;
              elements.forEach((item, position) => {
                const index =
                  kind === "nodes"
                    ? model.nodes.findIndex(({ id }) => id === item.getAttribute("data-node-id"))
                    : position;
                if (index < 0) return;
                const entry = model[kind][index];
                const label =
                  kind === "nodes"
                    ? entry.label
                    : [
                        model.nodes.find(({ id }) => id === entry.from)?.label,
                        model.nodes.find(({ id }) => id === entry.to)?.label,
                        entry.label,
                      ]
                        .filter(Boolean)
                        .join(" → ");
                item.setAttribute("aria-label", label);
                item.setAttribute("role", "button");
                item.setAttribute("tabindex", "0");
                item.dataset.diagramPick = kind;
                item.dataset.diagramIndex = String(index);
                if (kind === "edges") {
                  const target = item.querySelector("path")?.cloneNode();
                  if (target) {
                    target.removeAttribute("marker-end");
                    target.classList.add("cm-diagram-edge-hit");
                    item.prepend(target);
                  }
                }
                if (focusKey?.diagramPick === kind && focusKey.diagramIndex === String(index))
                  item.focus({ preventScroll: true });
              });
            }
            reflectCanvas();
          }
          if (source === this.source && !widget.querySelector(".cm-diagram-controls[open]")) {
            view.requestMeasure({
              read: () => (widget.isConnected ? widget.offsetHeight + 16 : 0),
              write: (height) => {
                if (!height) return;
                if (measuredDiagramHeights.size >= 48 && !measuredDiagramHeights.has(source))
                  measuredDiagramHeights.delete(measuredDiagramHeights.keys().next().value);
                measuredDiagramHeights.set(source, height);
              },
            });
          }
        } else
          canvas.textContent = t(
            "Preview unavailable for this diagram.",
            "پیش‌نمایش این نمودار در دسترس نیست.",
          );
      } catch {
        if (revision !== previewRevision) return;
        canvas.textContent = t(
          "Could not load the diagram preview.",
          "پیش‌نمایش نمودار بارگیری نشد.",
        );
      }
      view.requestMeasure();
    };
    void render();
    widget.append(header, canvas);
    if (this.readOnly) return widget;
    if (!model) {
      const note = document.createElement("p");
      note.className = "cm-diagram-note";
      note.textContent = t(
        "Visual editing is available for supported flowcharts.",
        "ویرایش بصری برای فلوچارت‌های پشتیبانی‌شده در دسترس است.",
      );
      widget.append(note);
      return widget;
    }
    const editor = document.createElement("details");
    let editorDrawn = false;
    editor.className = "cm-diagram-controls";
    const summary = document.createElement("summary");
    summary.textContent = t("Edit diagram", "ویرایش نمودار");
    const items = document.createElement("div");
    const direction = document.createElement("div");
    direction.className = "cm-diagram-direction";
    const tools = document.createElement("div");
    tools.className = "cm-diagram-tools";
    const instruction = document.createElement("span");
    instruction.setAttribute("role", "status");
    const visualTools = document.createElement("div");
    visualTools.className = "cm-diagram-tools-panel";
    visualTools.hidden = true;
    visualTools.append(tools, instruction);
    widget.insertBefore(visualTools, canvas);
    const groups = {};
    for (const [key, label] of [
      ["nodes", t("Nodes", "گره‌ها")],
      ["edges", t("Connections", "اتصال‌ها")],
    ]) {
      const group = document.createElement("details");
      group.className = "cm-diagram-group";
      group.open = key === "nodes";
      const header = document.createElement("summary");
      const body = document.createElement("div");
      header.textContent = label;
      const count = document.createElement("span");
      header.append(count);
      group.append(header, body);
      groups[key] = { body, count };
      items.append(group);
      group.addEventListener("toggle", () => view.requestMeasure());
    }
    items.prepend(direction);
    const footer = document.createElement("footer");
    editor.append(summary, items, footer);
    widget.append(editor);
    const button = (parent, label, action, icon) => {
      const item = document.createElement("button");
      item.type = "button";
      item.ariaLabel = item.title = label;
      if (icon) item.append(spriteIcon(icon));
      if (icon !== "trash") item.append(label);
      else item.classList.add("cm-diagram-delete");
      item.addEventListener("click", action);
      parent.append(item);
      return item;
    };
    const field = (parent, label, control) => {
      const wrapper = document.createElement("label");
      wrapper.textContent = label;
      wrapper.append(control);
      parent.append(wrapper);
    };
    const text = (value, apply) => {
      const input = document.createElement("input");
      input.value = value;
      input.dir = "auto";
      input.addEventListener("input", () => apply(input.value));
      return input;
    };
    const select = (choices, active, apply) => {
      const control = document.createElement("select");
      for (const [key, label] of choices) control.add(new Option(label, key));
      control.value = active;
      control.addEventListener("change", () => apply(control.value));
      return control;
    };
    const valid = () =>
      model.nodes.length &&
      !model.nodes.some(
        ({ label, shape }) => /[";\r\n]|%%/.test(label) || label.includes(shapes[shape][1]),
      ) &&
      !model.edges.some(({ label }) => /[|;\r\n]|%%/.test(label));
    const queuePreview = () => {
      clearTimeout(previewTimer);
      if (valid()) previewTimer = setTimeout(() => void render(diagramSource(model)), 210);
    };
    const setConnecting = (enabled) => {
      connecting = enabled;
      startNode = null;
      connect.setAttribute("aria-pressed", String(connecting));
      canvas.classList.toggle("cm-diagram-connecting", connecting);
      instruction.textContent = connecting
        ? t("Choose the first node.", "گره مبدأ را انتخاب کن.")
        : "";
      reflectCanvas();
    };
    const reflectSelection = () => {
      for (const [kind, group] of Object.entries(groups)) {
        group.body.classList.toggle("cm-diagram-filtered", selection?.kind === kind);
        Array.from(group.body.querySelectorAll(".cm-diagram-fields")).forEach((row, index) => {
          row.classList.toggle(
            "cm-diagram-field-selected",
            selection?.kind === kind && selection.index === index,
          );
        });
        if (selection) group.body.parentElement.open = selection.kind === kind;
      }
      showAll.hidden = !selection;
      reflectCanvas();
      view.requestMeasure();
    };
    const pick = (target, focus) => {
      const kind = target.dataset.diagramPick;
      const index = Number(target.dataset.diagramIndex);
      if (!model[kind]?.[index]) return;
      if (!editor.open) {
        editor.open = true;
        draw();
      }
      if (connecting) {
        if (kind !== "nodes") return;
        const id = model.nodes[index].id;
        if (!startNode) {
          startNode = id;
          instruction.textContent = t("Choose the destination node.", "گره مقصد را انتخاب کن.");
          reflectCanvas();
          return;
        }
        model.edges.push({ from: startNode, to: id, kind: "-->", label: "" });
        selection = { kind: "edges", index: model.edges.length - 1 };
        setConnecting(false);
        draw();
        queuePreview();
      } else {
        selection = { kind, index };
        reflectSelection();
      }
      if (focus)
        groups[selection.kind].body.querySelector(".cm-diagram-field-selected input")?.focus();
    };
    canvas.addEventListener("click", (event) => {
      const target = event.target.closest("[data-diagram-pick]");
      if (target) pick(target, event.detail > 1);
    });
    canvas.addEventListener("keydown", (event) => {
      const target = event.target.closest("[data-diagram-pick]");
      if (target && ["Enter", " "].includes(event.key)) {
        event.preventDefault();
        event.stopPropagation();
        pick(target, !connecting);
      } else if (event.key === "Escape" && connecting) {
        event.stopPropagation();
        setConnecting(false);
      }
    });
    const addNode = () => {
      let number = model.nodes.length + 1;
      while (model.nodes.some((node) => node.id === "node" + number)) number += 1;
      model.nodes.push({ id: "node" + number, label: t("New node", "گره جدید"), shape: "rect" });
      selection = { kind: "nodes", index: model.nodes.length - 1 };
      draw();
      const label = groups.nodes.body.querySelector(".cm-diagram-field-selected input");
      label?.focus();
      label?.select();
      queuePreview();
    };
    button(tools, t("Add node", "افزودن گره"), addNode, "plus");
    const connect = button(
      tools,
      t("Connect nodes", "اتصال گره‌ها"),
      () => setConnecting(!connecting),
      "link",
    );
    connect.setAttribute("aria-pressed", "false");
    const showAll = button(tools, t("Show all properties", "نمایش همهٔ ویژگی‌ها"), () => {
      selection = null;
      reflectSelection();
    });
    showAll.hidden = true;
    const draw = () => {
      editorDrawn = true;
      direction.replaceChildren();
      for (const [key, { body, count }] of Object.entries(groups)) {
        body.replaceChildren();
        count.textContent = String(model[key].length);
      }
      field(
        direction,
        t("Direction", "جهت"),
        select(
          [
            ["TD", t("Top to bottom", "بالا به پایین")],
            ["TB", t("Top to bottom", "بالا به پایین")],
            ["LR", t("Left to right", "چپ به راست")],
            ["RL", t("Right to left", "راست به چپ")],
            ["BT", t("Bottom to top", "پایین به بالا")],
          ].filter(([value]) => value !== (model.direction === "TB" ? "TD" : "TB")),
          model.direction,
          (value) => {
            model.direction = value;
            queuePreview();
          },
        ),
      );
      for (const node of model.nodes) {
        const row = document.createElement("div");
        row.className = "cm-diagram-fields";
        field(
          row,
          t("Node label", "نام گره"),
          text(node.label, (value) => {
            node.label = value;
            groups.edges.body.querySelectorAll("select[data-endpoint] option").forEach((option) => {
              if (option.value === node.id) option.textContent = value || node.id;
            });
            queuePreview();
          }),
        );
        field(
          row,
          t("Shape", "شکل"),
          select(
            Object.entries(shapes).map(([key, [, , en, persian]]) => [key, t(en, persian)]),
            node.shape,
            (value) => {
              node.shape = value;
              queuePreview();
            },
          ),
        );
        button(
          row,
          t("Remove node", "حذف گره"),
          () => {
            model.nodes = model.nodes.filter((item) => item !== node);
            model.edges = model.edges.filter(({ from, to }) => from !== node.id && to !== node.id);
            selection = null;
            setConnecting(false);
            draw();
            queuePreview();
          },
          "trash",
        );
        groups.nodes.body.append(row);
      }
      for (const edge of model.edges) {
        const row = document.createElement("div");
        row.className = "cm-diagram-fields";
        const choices = model.nodes.map(({ id, label }) => [id, label]);
        for (const [key, title] of [
          ["from", t("From", "از")],
          ["to", t("To", "به")],
        ]) {
          const control = select(choices, edge[key], (value) => {
            edge[key] = value;
            queuePreview();
          });
          control.dataset.endpoint = key;
          field(row, title, control);
        }
        const label = text(edge.label, (value) => {
          edge.label = value;
          queuePreview();
        });
        label.disabled = edge.kind === "---";
        field(
          row,
          t("Connector", "نوع اتصال"),
          select(
            [
              ["-->", t("Arrow", "پیکان")],
              ["-.->", t("Dotted arrow", "پیکان نقطه‌چین")],
              ["==>", t("Thick arrow", "پیکان ضخیم")],
              ["---", t("Line", "خط")],
            ],
            edge.kind,
            (value) => {
              edge.kind = value;
              label.disabled = value === "---";
              queuePreview();
            },
          ),
        );
        field(row, t("Label", "برچسب"), label);
        button(
          row,
          t("Remove connection", "حذف اتصال"),
          () => {
            model.edges = model.edges.filter((item) => item !== edge);
            selection = null;
            draw();
            queuePreview();
          },
          "trash",
        );
        groups.edges.body.append(row);
      }
      const add = button(
        groups.edges.body,
        t("Add connection", "افزودن اتصال"),
        () => {
          model.edges.push({
            from: model.nodes[0].id,
            to: model.nodes[1].id,
            kind: "-->",
            label: "",
          });
          draw();
          queuePreview();
        },
        "plus",
      );
      add.disabled = model.nodes.length < 2;
      connect.disabled = model.nodes.length < 2;
      reflectSelection();
    };
    const message = document.createElement("p");
    message.setAttribute("role", "alert");
    footer.append(message);
    button(footer, t("Cancel", "لغو"), () => {
      editor.open = false;
    });
    const apply = button(
      footer,
      t("Apply diagram changes", "اعمال تغییرات نمودار"),
      () => {
        if (view.state.readOnly || codeBodyText(view.state, this.spec) !== this.source) return;
        if (!valid()) {
          message.textContent = t(
            "Enter compatible labels and keep at least one node.",
            "برچسب سازگار وارد کن و دست‌کم یک گره نگه دار.",
          );
          return;
        }
        const replacement = diagramSource(model);
        if (replacement === originalModelSource) {
          editor.open = false;
          return;
        }
        const insert =
          replacement
            .split("\n")
            .map((line) => this.spec.bodyPrefix + line)
            .join("\n") + (this.spec.closeFrom == null ? "" : "\n");
        view.dispatch({
          changes: { from: this.spec.bodyFrom, to: this.spec.bodyTo, insert },
          selection: { anchor: this.spec.from },
          scrollIntoView: true,
          annotations: [Transaction.userEvent.of("input.diagram"), isolateHistory.of("full")],
        });
        view.focus();
      },
      "check",
    );
    apply.className = "cm-diagram-apply";
    const originalModelSource = diagramSource(model);
    editor.addEventListener("toggle", () => {
      visualTools.hidden = !editor.open;
      if (editor.open) {
        if (!editorDrawn) draw();
      } else {
        editorDrawn = false;
        clearTimeout(previewTimer);
        selection = null;
        setConnecting(false);
        model = diagramModel(this.source);
        message.textContent = "";
        void render();
        view.requestMeasure();
      }
    });
    return widget;
  }
}
