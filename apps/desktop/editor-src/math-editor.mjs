import { Facet, Transaction } from "@codemirror/state";
import { isolateHistory } from "@codemirror/commands";
import { editorDialog } from "./editor-dialog.mjs";

export const mathRenderer = Facet.define({ combine: (values) => values[0] || null });

const templates = [
  [
    "½",
    "Fraction",
    "کسر",
    [
      ["Numerator", "صورت"],
      ["Denominator", "مخرج"],
    ],
    ([a, b]) => "\\frac{" + a + "}{" + b + "}",
  ],
  ["√", "Root", "جذر", [["Radicand", "عبارت زیر رادیکال"]], ([a]) => "\\sqrt{" + a + "}"],
  [
    "x²",
    "Power",
    "توان",
    [
      ["Base", "پایه"],
      ["Exponent", "توان"],
    ],
    ([a, b]) => a + "^{" + b + "}",
  ],
  [
    "x₁",
    "Subscript",
    "زیروند",
    [
      ["Base", "پایه"],
      ["Index", "اندیس"],
    ],
    ([a, b]) => a + "_{" + b + "}",
  ],
  [
    "∑",
    "Sum",
    "مجموع",
    [
      ["Lower limit", "حد پایین"],
      ["Upper limit", "حد بالا"],
      ["Term", "جمله"],
    ],
    ([a, b, c]) => "\\sum_{" + a + "}^{" + b + "} " + c,
  ],
  [
    "∫",
    "Integral",
    "انتگرال",
    [
      ["Lower limit", "حد پایین"],
      ["Upper limit", "حد بالا"],
      ["Integrand", "عبارت انتگرال"],
    ],
    ([a, b, c]) => "\\int_{" + a + "}^{" + b + "} " + c,
  ],
];

export function mathMarkup(expression, display) {
  return display ? "$$\n" + expression + "\n$$" : "$" + expression + "$";
}

export function openMathEditor(view, { display, expression, apply: commit }) {
  if (view.state.readOnly) return false;
  const renderer = view.state.facet(mathRenderer);
  const t = (en, fa) => (document.documentElement.lang.startsWith("fa") ? fa : en);
  const panel = editorDialog(
    view,
    display ? t("Display equation", "فرمول مستقل") : t("Inline equation", "فرمول درون‌متنی"),
  );
  panel.dialog.classList.add("cm-math-dialog");
  const input = document.createElement(display ? "textarea" : "input");
  if (display) input.rows = 3;
  input.dir = "ltr";
  input.spellcheck = false;
  input.autofocus = true;
  input.value = expression;
  const label = document.createElement("label");
  label.textContent = t("Expression", "عبارت ریاضی");
  label.append(input);
  const toolbar = document.createElement("div");
  toolbar.className = "cm-math-templates";
  toolbar.setAttribute("role", "group");
  toolbar.setAttribute("aria-label", t("Formula templates", "الگوهای فرمول"));
  const fields = document.createElement("div");
  fields.className = "cm-math-template-fields";
  fields.hidden = true;
  const preview = document.createElement("div");
  preview.className = "cm-math-dialog-preview";
  preview.setAttribute("aria-label", t("Equation preview", "پیش‌نمایش فرمول"));
  let revision = 0;
  let timer = 0;
  const update = () => {
    clearTimeout(timer);
    const version = ++revision;
    const draft = input.value.trim();
    const valid = draft && draft.length <= 16384 && !/(^|[^\\])\$/.test(draft);
    panel.apply.disabled = !valid || Boolean(renderer);
    panel.message.textContent =
      draft && !valid
        ? t("Enter an expression without dollar delimiters.", "عبارت را بدون علامت دلار وارد کن.")
        : "";
    if (!valid) {
      preview.replaceChildren();
      return;
    }
    timer = setTimeout(async () => {
      const formula = document.createElement("span");
      formula.className = "math " + (display ? "display" : "inline");
      formula.textContent = mathMarkup(draft, display);
      preview.replaceChildren(formula);
      const current = () => panel.dialog.open && version === revision;
      try {
        await renderer?.(preview, { isCurrent: current });
      } catch {
        if (current()) formula.dataset.mathError = "true";
      }
      if (!current()) return;
      const error = formula.dataset.mathError === "true";
      panel.apply.disabled = error;
      if (error)
        panel.message.textContent = t(
          "Check the formula before applying.",
          "عبارت فرمول را بررسی کن.",
        );
    }, 100);
  };
  const insert = (content, start, end) => {
    input.setRangeText(content, start, end, "end");
    input.focus();
    update();
  };
  for (const [glyph, en, fa, params, make] of templates) {
    const control = document.createElement("button");
    control.type = "button";
    control.textContent = glyph;
    control.title = control.ariaLabel = t(en, fa);
    control.addEventListener("click", () => {
      const start = input.selectionStart;
      const end = input.selectionEnd;
      fields.replaceChildren();
      const inputs = params.map(([en, fa], index) => {
        const label = document.createElement("label");
        label.textContent = t(en, fa);
        const field = document.createElement("input");
        field.dir = "ltr";
        field.value = index === 0 ? input.value.slice(start, end) : "";
        label.append(field);
        fields.append(label);
        return field;
      });
      const add = document.createElement("button");
      add.type = "button";
      add.className = "button secondary";
      add.textContent = t("Insert template", "درج الگو");
      add.addEventListener("click", () => {
        if (inputs.some((field) => !field.value.trim())) {
          inputs.find((field) => !field.value.trim()).focus();
          return;
        }
        fields.hidden = true;
        insert(make(inputs.map((field) => field.value.trim())), start, end);
      });
      fields.append(add);
      fields.hidden = false;
      inputs[0].focus();
    });
    toolbar.append(control);
  }
  for (const glyph of ["π", "∞", "≤", "≥", "≠", "×", "±"]) {
    const control = document.createElement("button");
    control.type = "button";
    control.textContent = glyph;
    control.addEventListener("click", () =>
      insert(glyph, input.selectionStart, input.selectionEnd),
    );
    toolbar.append(control);
  }
  input.addEventListener("input", update);
  panel.dialog.addEventListener("close", () => clearTimeout(timer));
  panel.body.append(label, toolbar, fields, preview);
  panel.open(() => !panel.apply.disabled && commit(mathMarkup(input.value.trim(), display)));
  update();
  return true;
}

export function updateMath(view, from, to, insert, original) {
  if (view.state.readOnly || view.state.sliceDoc(from, to) !== original) return false;
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + insert.length },
    annotations: [Transaction.userEvent.of("input.math"), isolateHistory.of("full")],
  });
  return true;
}
