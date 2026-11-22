import { enableDialogBackdrop } from "../../ui/dialog-backdrop.mjs";
import { element, libraryIcon, shelfObject, useHandwriting } from "./objects.mjs";
import {
  choices,
  defaults,
  FONT_SOURCE_LIMIT,
  noteColor,
  notePalette,
  palette,
  paperKey,
} from "./appearance-options.mjs";

const fields = {
  book: ["variant", "texture", "color", "pattern", "picture", "mark", "logo"],
  document: ["fastener", "letterhead", "sheets", "mark", "logo", "chart", "color"],
  note: ["material", "color", "ruling", "tape", "handFont"],
  resume: ["avatar", "picture"],
  article: ["binding", "color", "pattern", "picture"],
};
const buttonChoices = new Set([
  "variant",
  "texture",
  "fastener",
  "material",
  "binding",
  "avatar",
  "privacy",
]);

async function thumbnail(file) {
  if (
    !file ||
    file.size > 10 * 1024 * 1024 ||
    !["image/jpeg", "image/png", "image/webp"].includes(file.type)
  )
    throw new Error("image");
  const url = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  const img = new Image();
  img.src = url;
  await img.decode();
  const scale = Math.min(1, 280 / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  const data = canvas.toDataURL("image/jpeg", 0.74);
  if (data.length > 98304 || !data.startsWith("data:image/jpeg;")) throw new Error("image");
  return data;
}
async function fontSource(file) {
  const format = /\.(woff2?|ttf|otf)$/i.exec(file.name)?.[1].toLowerCase();
  if (!format || Math.ceil(file.size / 3) * 4 + 24 > FONT_SOURCE_LIMIT) throw new Error("font");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const data =
    "data:font/" +
    format +
    ";base64," +
    btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""));
  if (!(await useHandwriting(data))) throw new Error("font");
  return data;
}

export function editAppearance(item, t, save, restore) {
  let type = item.type;
  const dialog = element("dialog", "library-form library-appearance");
  const form = element("form");
  const title = element("h2", "", t("shelfAppearance"));
  title.id = "shelf-appearance-heading";
  dialog.setAttribute("aria-labelledby", title.id);
  const section = element("div", "library-appearance-main");
  const body = element("div", "library-form-fields");
  const values = { ...item.appearance };
  const proof = element("aside", "library-proof-panel");
  const stage = element("button", "library-proof");
  const sample = element("span", "library-specimen");
  const proofLabel = element("span", "library-proof-label", t("shelfLiveProof"));
  stage.type = "button";
  stage.setAttribute("aria-label", t("shelfAnimate"));
  stage.setAttribute("aria-pressed", "false");
  stage.append(sample);
  stage.addEventListener("click", () =>
    stage.setAttribute("aria-pressed", String(stage.getAttribute("aria-pressed") === "false")),
  );
  proof.append(proofLabel, stage);
  section.append(body, proof);
  const error = element("div", "library-form-error");
  error.setAttribute("role", "alert");
  const actions = element("div", "library-form-actions");
  const reset = element("button", "library-action", t("shelfAuto"));
  const cancel = element("button", "library-action", t("cancel"));
  const apply = element("button", "button primary", t("save"));
  reset.type = cancel.type = "button";
  apply.type = "submit";
  let busy = 0;
  let saving = false;

  function disabled() {
    apply.disabled = Boolean(busy) || saving;
    reset.disabled = Boolean(busy) || saving;
    cancel.disabled = saving;
    const typeSelect = body.querySelector("#shelf-appearance-type");
    if (typeSelect) typeSelect.disabled = Boolean(busy) || saving;
  }
  function updateProof() {
    stage.dataset.type = type;
    sample.replaceChildren(shelfObject({ ...item, type, appearance: values }, t));
  }
  function change(key, value) {
    if (value) values[key] = value;
    else delete values[key];
    updateProof();
  }
  function choiceGroup(key, fieldLabel, value) {
    const group = element("fieldset", "library-appearance-choices wide");
    const legend = element("legend", "", fieldLabel);
    const row = element("div", key === "texture" ? "library-textures" : "library-choice-row");
    for (const option of choices[key]) {
      const button = element("button", "library-action");
      button.type = "button";
      button.value = option;
      button.setAttribute("aria-pressed", String(option === value));
      if (key === "texture") {
        const chip = element("span", "library-texture-chip");
        chip.dataset.texture = option;
        chip.style.backgroundColor = values.color || defaults(type).color;
        chip.append(element("span", "folio-cover-skin"));
        button.append(chip);
      }
      button.append(element("span", "", t("sv" + option)));
      button.addEventListener("click", () => {
        if (key === "material") {
          values.material = option;
          build();
          body.querySelector(`[data-field="material"] button[value="${option}"]`)?.focus();
          return;
        }
        change(key, option);
        for (const peer of row.children) peer.setAttribute("aria-pressed", String(peer === button));
      });
      row.append(button);
    }
    group.dataset.field = key;
    group.append(legend, row);
    return group;
  }
  function pressColors(key, selected, list) {
    for (const button of list.querySelectorAll("button"))
      button.setAttribute("aria-pressed", String(button.value === selected.toLowerCase()));
    const input = list.querySelector("input");
    input.value = selected;
    if (key === "color") {
      for (const chip of body.querySelectorAll(".library-texture-chip"))
        chip.style.backgroundColor = selected;
    }
  }
  function colors(fieldLabel) {
    const a = { ...defaults(type), ...values };
    const isNote = type === "note";
    const key = isNote ? paperKey(a.material) : "color";
    const group = element("fieldset", "library-appearance-choices wide");
    const list = element("div", "library-swatches");
    const input = element("input", "library-custom-color");
    input.type = "color";
    input.title = t("shelfCustomColor");
    input.setAttribute("aria-label", input.title);
    function select(color) {
      change(key, color);
      pressColors(key, color, list);
    }
    for (const color of isNote ? notePalette : palette) {
      const button = element("button", "library-swatch");
      button.type = "button";
      button.value = color;
      button.title = color;
      button.setAttribute("aria-label", fieldLabel + " " + color);
      button.style.setProperty("--swatch", color);
      button.addEventListener("click", () => select(color));
      list.append(button);
    }
    input.addEventListener("input", () => select(input.value));
    list.append(input);
    pressColors(key, isNote ? noteColor(a) : a.color, list);
    group.append(element("legend", "", fieldLabel), list);
    return group;
  }
  function uploadControl(key, labelText) {
    const group = element("fieldset", "library-appearance-choices wide");
    const row = element("div", "library-file-row");
    const input = element("input");
    const font = key === "handFont";
    const sourceKey = key + "Source";
    input.type = "file";
    input.accept = font ? ".woff2,.woff,.ttf,.otf" : "image/jpeg,image/png,image/webp";
    input.setAttribute("aria-label", labelText);
    const remove = element("button", "library-action", t("shelfClearUpload"));
    remove.type = "button";
    const sourceLabel = element("label", "library-upload-source");
    const source = element("select");
    for (const option of ["preset", "uploaded"]) {
      const entry = element("option", "", t("sv" + option));
      entry.value = option;
      source.append(entry);
    }
    source.addEventListener("change", () => change(sourceKey, source.value));
    sourceLabel.append(element("span", "", t("shelfDisplaySource")), source);
    function update() {
      remove.hidden = !values[key];
      sourceLabel.hidden = font || !values[key];
      source.value = values[sourceKey] || "uploaded";
    }
    remove.addEventListener("click", () => {
      delete values[key];
      delete values[sourceKey];
      input.value = "";
      update();
      updateProof();
    });
    input.addEventListener("change", async () => {
      if (!input.files[0]) return;
      busy++;
      input.disabled = remove.disabled = source.disabled = true;
      const materials = [...body.querySelectorAll('[data-field="material"] button')];
      for (const button of materials) button.disabled = true;
      disabled();
      error.textContent = "";
      try {
        values[key] = await (font ? fontSource(input.files[0]) : thumbnail(input.files[0]));
        if (!font) values[sourceKey] = "uploaded";
        update();
        updateProof();
      } catch {
        error.textContent = t(font ? "shelfFontError" : "shelfImageError");
      } finally {
        busy--;
        input.disabled = remove.disabled = source.disabled = false;
        for (const button of materials) button.disabled = false;
        disabled();
      }
    });
    row.append(input, remove);
    if (!font) row.append(sourceLabel);
    group.append(element("legend", "", labelText), row);
    update();
    return group;
  }
  function control(key) {
    const fieldLabel = t("sf" + key);
    const value = values[key] ?? defaults(type)[key];
    if (key === "color") return colors(type === "note" ? t("shelfPaperColor") : fieldLabel);
    if (buttonChoices.has(key)) return choiceGroup(key, fieldLabel, value);
    if (["picture", "logo", "handFont"].includes(key)) return uploadControl(key, fieldLabel);
    const label = element("label", choices[key] ? "" : "wide");
    label.append(element("span", "", fieldLabel));
    let input;
    if (choices[key]) {
      input = element("select");
      for (const option of choices[key]) {
        const text =
          key === "sheets"
            ? new Intl.NumberFormat(document.documentElement.lang).format(Number(option))
            : t("sv" + option);
        const entry = element("option", "", text);
        entry.value = option;
        input.append(entry);
      }
      input.value = value;
      input.addEventListener("change", () => change(key, input.value));
    } else {
      input = element("input");
      input.type = "text";
      input.maxLength = 180;
      input.dir = "auto";
      input.value = value || "";
      input.placeholder =
        key === "label"
          ? item.title || ""
          : key === "letterhead"
            ? item.organization || ""
            : "35, 55, 80";
      input.addEventListener("input", () => change(key, input.value));
    }
    label.append(input);
    if (key === "chart") label.append(element("small", "", t("shelfChartHint")));
    return label;
  }
  function build() {
    const keys = fields[type].filter((key) => key !== "tape" || values.material !== "cotton");
    body.replaceChildren(...["label", ...keys, "privacy"].map(control));
    if (item.type === "article" || item.type === "document") {
      const label = element("label", "wide");
      const select = element("select");
      select.id = "shelf-appearance-type";
      for (const value of ["document", "article"]) {
        const option = element("option", "", t("shelf" + value));
        option.value = value;
        select.append(option);
      }
      select.value = type;
      select.addEventListener("change", () => {
        type = select.value;
        build();
        body.querySelector("#shelf-appearance-type").focus();
      });
      label.append(element("span", "", t("shelfItemType")), select);
      body.prepend(label);
    }
    disabled();
    updateProof();
  }
  reset.addEventListener("click", () => {
    for (const key of Object.keys(values)) delete values[key];
    error.textContent = "";
    build();
  });
  cancel.addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", (event) => {
    if (saving) event.preventDefault();
  });
  dialog.addEventListener(
    "close",
    () => {
      dialog.remove();
      restore();
    },
    { once: true },
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || saving) return;
    saving = true;
    disabled();
    try {
      await save({ ...values }, type);
      dialog.close();
    } catch {
      error.textContent = t("shelfWriteError");
    } finally {
      saving = false;
      disabled();
    }
  });
  build();
  actions.append(reset, cancel, apply);
  title.prepend(libraryIcon("edit"));
  form.append(title, section, error, actions);
  dialog.append(form);
  document.body.append(dialog);
  enableDialogBackdrop(dialog, () => !saving);
  dialog.showModal();
}
