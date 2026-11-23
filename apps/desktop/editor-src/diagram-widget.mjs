import { Facet, Transaction } from "@codemirror/state";
import { WidgetType } from "@codemirror/view";
import { isolateHistory } from "@codemirror/commands";
import { codeBodyText } from "./code-block-tools.mjs";

export const diagramRenderer = Facet.define({ combine: (values) => values[0] || null });

const nodeSource =
  /^([A-Za-z_][\w.-]*)(?:\["?([^"\[\];]+)"?\]|\{"?([^"{};]+)"?\}|\("?([^"();]+)"?\))?$/;
const edgeSource = /^(.*?)\s*(-->|---|-.->|==>)\s*(?:\|([^|]+)\|\s*)?(.*?)$/;

/** Only offer editing when all source statements can be represented by the controls. */
export function diagramModel(source) {
  const lines = source
    .trim()
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const header = /^(graph|flowchart)\s+(TD|TB|LR|RL|BT)$/i.exec(lines.shift() || "");
  if (!header) return null;
  const nodes = new Map(),
    edges = [];
  function add(expression) {
    const match = nodeSource.exec(expression.trim());
    if (!match || /^(?:classDef|class|style|click|direction|end|subgraph)$/i.test(match[1]))
      return null;
    const [, id, rect, diamond, round] = match;
    if (!nodes.has(id) || rect || diamond || round)
      nodes.set(id, {
        id,
        label: rect ?? diamond ?? round ?? id,
        shape: diamond ? "diamond" : round ? "round" : "rect",
      });
    return id;
  }
  for (const line of lines) {
    const edge = edgeSource.exec(line);
    if (edge) {
      const from = add(edge[1]),
        to = add(edge[4]);
      if (!from || !to) return null;
      edges.push({ from, to, kind: edge[2], label: edge[3] || "" });
    } else if (!add(line)) return null;
  }
  return { direction: header[2].toUpperCase(), nodes: [...nodes.values()], edges };
}

export function diagramSource(model) {
  const labels = (value) => value.trim();
  const nodes = model.nodes.map(({ id, label, shape }) => {
    const [left, right] = { rect: ["[", "]"], diamond: ["{", "}"], round: ["(", ")"] }[shape];
    return "  " + id + left + '"' + (labels(label) || id) + '"' + right;
  });
  const edges = model.edges.map(
    ({ from, to, kind, label }) =>
      "  " + from + " " + kind + (labels(label) ? "|" + labels(label) + "|" : "") + " " + to,
  );
  return ["flowchart " + model.direction, ...nodes, ...edges].join("\n");
}

export class DiagramWidget extends WidgetType {
  constructor(source, spec, renderer, readOnly) {
    super();
    this.source = source;
    this.spec = spec;
    this.renderer = renderer;
    this.readOnly = readOnly;
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
    return 210;
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
    const model = diagramModel(this.source);
    const render = async () => {
      try {
        const svg = await this.renderer?.(this.source);
        if (svg) canvas.replaceChildren(svg);
        else
          canvas.textContent = t(
            "Preview unavailable for this diagram.",
            "پیش‌نمایش این نمودار در دسترس نیست.",
          );
      } catch {
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
    editor.className = "cm-diagram-controls";
    const summary = document.createElement("summary");
    summary.textContent = t("Edit diagram", "ویرایش نمودار");
    const items = document.createElement("div");
    editor.append(summary, items);
    widget.append(editor);
    const button = (parent, label, action) => {
      const item = document.createElement("button");
      item.type = "button";
      item.textContent = label;
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
    const draw = () => {
      items.replaceChildren();
      field(
        items,
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
          (value) => (model.direction = value),
        ),
      );
      for (const node of model.nodes) {
        const row = document.createElement("div");
        row.className = "cm-diagram-fields";
        field(
          row,
          t("Node label", "نام گره"),
          text(node.label, (value) => (node.label = value)),
        );
        field(
          row,
          t("Shape", "شکل"),
          select(
            [
              ["rect", t("Rectangle", "مستطیل")],
              ["diamond", t("Diamond", "لوزی")],
              ["round", t("Rounded", "گرد")],
            ],
            node.shape,
            (value) => (node.shape = value),
          ),
        );
        button(row, t("Remove node", "حذف گره"), () => {
          model.nodes = model.nodes.filter((item) => item !== node);
          model.edges = model.edges.filter(({ from, to }) => from !== node.id && to !== node.id);
          draw();
        });
        items.append(row);
      }
      let number = model.nodes.length + 1;
      while (model.nodes.some((node) => node.id === "node" + number)) number += 1;
      button(items, t("Add node", "افزودن گره"), () => {
        model.nodes.push({ id: "node" + number, label: t("New node", "گره جدید"), shape: "rect" });
        draw();
      });
      for (const edge of model.edges) {
        const row = document.createElement("div");
        row.className = "cm-diagram-fields";
        const choices = model.nodes.map(({ id, label }) => [id, label]);
        field(
          row,
          t("From", "از"),
          select(choices, edge.from, (value) => (edge.from = value)),
        );
        field(
          row,
          t("To", "به"),
          select(choices, edge.to, (value) => (edge.to = value)),
        );
        field(
          row,
          t("Label", "برچسب"),
          text(edge.label, (value) => (edge.label = value)),
        );
        button(row, t("Remove connection", "حذف اتصال"), () => {
          model.edges = model.edges.filter((item) => item !== edge);
          draw();
        });
        items.append(row);
      }
      const add = button(items, t("Add connection", "افزودن اتصال"), () => {
        model.edges.push({
          from: model.nodes[0].id,
          to: model.nodes[1].id,
          kind: "-->",
          label: "",
        });
        draw();
      });
      add.disabled = model.nodes.length < 2;
      const message = document.createElement("p");
      message.setAttribute("role", "alert");
      const apply = button(items, t("Apply diagram changes", "اعمال تغییرات نمودار"), () => {
        if (view.state.readOnly || codeBodyText(view.state, this.spec) !== this.source) return;
        const invalidNode = model.nodes.some(
          ({ label, shape }) =>
            /[";\r\n]|%%/.test(label) ||
            (shape === "rect"
              ? /[\[\]]/.test(label)
              : shape === "round"
                ? /[()]/.test(label)
                : /[{}]/.test(label)),
        );
        const invalidEdge = model.edges.some(({ label }) => /[|;\r\n]|%%/.test(label));
        if (invalidNode || invalidEdge || !model.nodes.length) {
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
          annotations: [Transaction.userEvent.of("input.diagram"), isolateHistory.of("full")],
        });
      });
      apply.className = "cm-diagram-apply";
      items.append(message);
      view.requestMeasure();
    };
    const originalModelSource = diagramSource(model);
    editor.addEventListener("toggle", () => {
      if (editor.open) draw();
      else view.requestMeasure();
    });
    return widget;
  }
}
