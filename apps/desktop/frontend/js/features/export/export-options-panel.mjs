import {
  OPTION_FIELDS, OPTION_GROUPS, collectRenderOptions, fieldIsActive,
  modifiedCountsByGroup, modifiedKeys, searchOptions, validateOptionValue,
} from "./render-options.mjs";
import { spriteIcon } from "../../ui/icons.mjs";
import { bindRadioGroup } from "../../ui/radio-group.mjs";

/** Publication colors, checked against appearance.PALETTES by test_desktop_app.py. */
const PALETTE_ACCENTS = Object.freeze({
  blue: "#2563eb",
  emerald: "#047857",
  violet: "#7c3aed",
  amber: "#b45309",
  rose: "#e11d48",
  slate: "#475569",
  neutral: "#404040",
});

/**
 * Own the publishing settings draft and its controls.
 * The shell supplies translation, the selected preset, and native path picking.
 * Rendering the panel alone never changes the export request.
 */
export function createExportOptionsPanel({
  root, t, getPresetOptions, onChange, pickPath, onError,
}) {
  const documentRef = root.ownerDocument;
  const $ = (selector) => root.querySelector(selector);
  const lifecycle = new documentRef.defaultView.AbortController();
  /**
   * Values the user has typed into the settings panel, keyed by option.
   *
   * Absent means "inherit"; the panel never sends a key the user did not touch,
   * so opening it cannot overwrite what mardas.toml already configured.
   */
  const advancedValues = new Map();

  /** Which category the settings browser is showing. */
  let activeOptionGroup = OPTION_GROUPS[0].id;
  let optionSearchQuery = "";
  let showExpertOptions = false;

  function advancedControlId(key) {
    return `adv-${key.replaceAll("_", "-")}`;
  }

  /** A translated label for an engine enum value, falling back to the identifier. */
  function choiceLabel(value) {
    const label = t(value);
    return label === value ? value : label;
  }

  function optionControlIdentity(control) {
    if (!control) return "";
    if (control.id) return `id:${control.id}`;
    const role = control.getAttribute("role") || control.tagName;
    const label = control.getAttribute("aria-label");
    if (label) return `${role}:${label}`;
    return `${role}:${control.className}:${control.textContent.trim()}`;
  }

  function setOptionValue(key, value) {
    if (lifecycle.signal.aborted) return;
    const active = documentRef.activeElement;
    const row = [...root.querySelectorAll("[data-option-key]")]
      .find((element) => element.dataset.optionKey === key);
    const controls = row ? [...row.querySelectorAll("input, select, textarea, button")] : [];
    const focusIndex = controls.indexOf(active);
    const focusIdentity = focusIndex >= 0 ? optionControlIdentity(active) : "";
    if (value === undefined) advancedValues.delete(key);
    else advancedValues.set(key, value);
    renderOptionCategories();
    renderOptionPane();
    if (focusIndex >= 0) {
      const nextRow = [...root.querySelectorAll("[data-option-key]")]
        .find((element) => element.dataset.optionKey === key);
      const nextControls = nextRow ? [...nextRow.querySelectorAll("input, select, textarea, button")] : [];
      const nextControl = nextControls.find((control) => optionControlIdentity(control) === focusIdentity)
        || nextControls[focusIndex]
        || nextRow?.querySelector("input, select, textarea, button");
      nextControl?.focus({ preventScroll: true });
    }
    onChange();
  }

  /** Omitted, false, and true remain distinct in the engine request. */
  function buildToggleControl(field) {
    const group = documentRef.createElement("div");
    group.className = "tri-toggle";
    group.setAttribute("role", "radiogroup");
    group.setAttribute("aria-labelledby", `${advancedControlId(field.key)}-label`);
    const current = advancedValues.has(field.key) ? Boolean(advancedValues.get(field.key)) : null;
    const states = [
      [null, t("inherit"), "—"],
      [false, t("off"), t("off")],
      [true, t("on"), t("on")],
    ];
    const buttons = states.map(([, label, text]) => {
      const button = documentRef.createElement("button");
      button.type = "button";
      button.className = "tri-toggle-option";
      button.setAttribute("aria-label", label);
      button.textContent = text;
      group.append(button);
      return button;
    });
    bindRadioGroup(group, {
      buttons,
      selectedIndex: states.findIndex(([value]) => current === value),
      onSelect(index) {
        setOptionValue(field.key, states[index][0] ?? undefined);
        focusRadio(field.key, index);
      },
    });
    return group;
  }

  function focusRadio(key, index) {
    root.querySelector(`[data-option-key="${key}"] [role="radiogroup"]`)
      ?.querySelectorAll('[role="radio"]')[index]?.focus({ preventScroll: true });
  }

  function buildSelectControl(field) {
    const control = documentRef.createElement("select");
    control.id = advancedControlId(field.key);
    const inherit = documentRef.createElement("option");
    inherit.value = "";
    inherit.textContent = `— ${t("inherit")}`;
    control.append(inherit);
    for (const choice of field.choices) {
      const option = documentRef.createElement("option");
      option.value = choice;
      option.textContent = choiceLabel(choice);
      control.append(option);
    }
    control.value = advancedValues.has(field.key) ? String(advancedValues.get(field.key)) : "";
    control.addEventListener("change", () => {
      setOptionValue(field.key, control.value === "" ? undefined : control.value);
    });
    return control;
  }

  /** A palette is a colour decision, so it is made against colour. */
  function buildSwatchControl(field) {
    const wrapper = documentRef.createElement("div");
    wrapper.className = "swatch-row";
    wrapper.setAttribute("role", "radiogroup");
    wrapper.setAttribute("aria-labelledby", `${advancedControlId(field.key)}-label`);
    const current = advancedValues.get(field.key) ?? "";
    const choices = ["", ...field.choices];
    const buttons = choices.map((choice) => {
      const button = documentRef.createElement("button");
      button.type = "button";
      button.className = "swatch";
      button.setAttribute("aria-label", choice ? choiceLabel(choice) : t("inherit"));
      button.title = button.getAttribute("aria-label");
      if (choice) button.style.setProperty("--swatch", PALETTE_ACCENTS[choice]);
      else {
        button.classList.add("swatch-inherit");
        button.textContent = "—";
      }
      wrapper.append(button);
      return button;
    });
    bindRadioGroup(wrapper, {
      buttons,
      selectedIndex: choices.indexOf(current),
      onSelect(index) {
        setOptionValue(field.key, choices[index] || undefined);
        focusRadio(field.key, index);
      },
    });
    return wrapper;
  }

  function buildSliderControl(field) {
    const wrapper = documentRef.createElement("div");
    wrapper.className = "slider-row";
    const slider = documentRef.createElement("input");
    slider.type = "range";
    slider.id = advancedControlId(field.key);
    slider.min = String(field.min ?? 0);
    slider.max = String(field.max ?? 1);
    slider.step = String(field.step ?? 0.05);
    const readout = documentRef.createElement("output");
    const stored = advancedValues.get(field.key);
    slider.value = String(stored ?? field.max ?? 1);
    readout.textContent = stored === undefined ? "—" : String(stored);
    slider.addEventListener("input", () => {
      readout.textContent = slider.value;
    });
    slider.addEventListener("change", () => setOptionValue(field.key, Number(slider.value)));
    wrapper.append(slider, readout);
    return wrapper;
  }

  function buildTextControl(field) {
    const wrapper = documentRef.createElement("div");
    wrapper.className = "text-row";
    const control = documentRef.createElement("input");
    control.id = advancedControlId(field.key);
    control.type = field.kind === "number" ? "number" : "text";
    if (field.min !== undefined) control.min = String(field.min);
    if (field.max !== undefined) control.max = String(field.max);
    if (field.step !== undefined) control.step = String(field.step);
    if (field.placeholder) control.placeholder = field.placeholder;
    if (field.kind === "path") control.dir = "ltr";
    control.value = advancedValues.has(field.key) ? String(advancedValues.get(field.key)) : "";
    const problem = documentRef.createElement("small");
    problem.className = "option-problem";
    problem.id = `${control.id}-problem`;
    control.setAttribute("aria-describedby", problem.id);

    let committing = false;
    const commit = () => {
      // Replacing a focused input can synchronously fire another native change.
      if (committing || lifecycle.signal.aborted) return;
      committing = true;
      try {
        const raw = control.value.trim();
        const complaint = raw ? validateOptionValue(field.key, raw) : null;
        problem.textContent = complaint ? t(complaint) : "";
        control.setAttribute("aria-invalid", String(Boolean(complaint)));
        wrapper.classList.toggle("has-problem", Boolean(complaint));
        // An invalid value is kept in the control so it can be corrected, but it is
        // never sent to the engine, which would only fail the render later.
        if (complaint) {
          advancedValues.delete(field.key);
          renderOptionCategories();
          onChange();
          return;
        }
        setOptionValue(field.key, raw === "" ? undefined : raw);
      } finally {
        committing = false;
      }
    };
    control.addEventListener("change", commit);

    wrapper.append(control);
    if (field.unit) {
      const unit = documentRef.createElement("span");
      unit.className = "option-unit";
      unit.textContent = field.unit;
      wrapper.append(unit);
    }
    if (field.kind === "path") {
      const browse = documentRef.createElement("button");
      browse.type = "button";
      browse.className = "button secondary compact";
      browse.textContent = t("browse");
      browse.addEventListener("click", async () => {
        browse.disabled = true;
        try {
          const picked = await pickPath(field);
          // A preset change, category change, or disposal invalidates this draft.
          if (!picked || !control.isConnected || lifecycle.signal.aborted) return;
          setOptionValue(field.key, picked);
        } catch (error) {
          if (control.isConnected && !lifecycle.signal.aborted) onError(error);
        } finally {
          browse.disabled = false;
        }
      });
      wrapper.append(browse);
    }
    wrapper.append(problem);
    return wrapper;
  }

  function buildOptionControl(field) {
    if (field.kind === "toggle") return buildToggleControl(field);
    if (field.widget === "swatches") return buildSwatchControl(field);
    if (field.widget === "slider") return buildSliderControl(field);
    if (field.kind === "select") return buildSelectControl(field);
    return buildTextControl(field);
  }

  function buildOptionRow(field, group) {
    const row = documentRef.createElement("div");
    row.className = "option-row";
    row.dataset.optionKey = field.key;
    // Track provenance so reset restores the preset instead of silently inheriting.
    const presetOptions = getPresetOptions();
    const hasValue = advancedValues.has(field.key);
    const fromPreset = hasValue
      && field.key in presetOptions
      && String(advancedValues.get(field.key)) === String(presetOptions[field.key]);
    const isSet = hasValue && !fromPreset;
    row.dataset.modified = String(isSet);
    row.dataset.source = isSet ? "override" : hasValue ? "preset" : "inherited";

    const head = documentRef.createElement("div");
    head.className = "option-head";
    const label = documentRef.createElement("label");
    label.className = "option-label";
    label.id = `${advancedControlId(field.key)}-label`;
    label.textContent = t(`opt.${field.key}`);
    if (field.kind !== "toggle" && field.widget !== "swatches") {
      label.setAttribute("for", advancedControlId(field.key));
    }
    head.append(label);

    if (field.risky) {
      const badge = documentRef.createElement("span");
      badge.className = "option-badge risky";
      badge.textContent = t("riskyBadge");
      head.append(badge);
    }
    if (fromPreset) {
      const badge = documentRef.createElement("span");
      badge.className = "option-badge from-preset";
      badge.textContent = t("fromPreset");
      head.append(badge);
    }
    if (isSet) {
      // Back to the preset's value where it has one, and to inherited where it
      // does not — which is what "reset" has to mean on a screen whose second
      // step is choosing a preset.
      const restores = field.key in presetOptions;
      const label = t(restores ? "resetToPreset" : "resetOption");
      const reset = documentRef.createElement("button");
      reset.type = "button";
      reset.className = "option-reset";
      reset.title = label;
      reset.setAttribute("aria-label", `${label}: ${t(`opt.${field.key}`)}`);
      reset.append(spriteIcon("close", documentRef));
      reset.addEventListener("click", () => setOptionValue(field.key, presetOptions[field.key]));
      head.append(reset);
    }

    const help = documentRef.createElement("p");
    help.className = "option-help";
    help.textContent = field.helpKey ? t(field.helpKey) : "";

    const active = fieldIsActive(field, Object.fromEntries(advancedValues), getPresetOptions());
    if (!active) {
      row.dataset.inactive = "true";
      const reason = documentRef.createElement("p");
      reason.className = "option-inactive";
      reason.textContent = t("inactiveOption").replace("%s", t(`opt.${field.dependsOn}`));
      row.append(head, help, buildOptionControl(field), reason);
      row.querySelectorAll("input, select, textarea, button").forEach((control) => {
        control.disabled = true;
      });
      if (group) row.dataset.group = group.id;
      return row;
    }

    row.append(head, help, buildOptionControl(field));
    if (group) row.dataset.group = group.id;
    return row;
  }

  /** Fields of a group the user should currently see. */
  function visibleFields(group) {
    return group.fields.filter((field) => showExpertOptions || !field.expert);
  }

  function renderOptionCategories() {
    const select = $("#option-category");
    const counts = modifiedCountsByGroup(
      Object.fromEntries(advancedValues),
      getPresetOptions(),
    );
    const groups = OPTION_GROUPS.filter((group) => showExpertOptions || !group.expert);
    const options = groups.map((group) => {
      const count = counts[group.id];
      return new documentRef.defaultView.Option(t(group.labelKey) + (count ? ` (${count})` : ""), group.id);
    });
    select.replaceChildren(...options);
    select.value = activeOptionGroup;
  }

  function renderOptionPane() {
    const pane = $("#option-pane");
    if (!pane) return;
    pane.replaceChildren();

    if (optionSearchQuery) {
      pane.setAttribute("aria-labelledby", "option-search-label");
      const matches = (searchOptions(optionSearchQuery, t) || [])
        .filter(({ field, group }) => showExpertOptions || (!field.expert && !group.expert));
      if (!matches.length) {
        const empty = documentRef.createElement("p");
        empty.className = "option-empty";
        empty.textContent = t("noOptionsMatch");
        pane.append(empty);
        return;
      }
      let lastGroup = null;
      for (const { group, field } of matches) {
        if (group !== lastGroup) {
          const caption = documentRef.createElement("p");
          caption.className = "option-search-group";
          caption.textContent = t(group.labelKey);
          pane.append(caption);
          lastGroup = group;
        }
        pane.append(buildOptionRow(field, group));
      }
      return;
    }

    const group = OPTION_GROUPS.find((item) => item.id === activeOptionGroup) || OPTION_GROUPS[0];
    pane.setAttribute("aria-labelledby", "option-category-title");
    const header = documentRef.createElement("header");
    header.className = "option-pane-head";
    const heading = documentRef.createElement("div");
    const title = documentRef.createElement("h3");
    title.id = "option-category-title";
    title.textContent = t(group.labelKey);
    const description = documentRef.createElement("small");
    description.textContent = group.descriptionKey ? t(group.descriptionKey) : "";
    heading.append(title, description);
    header.append(heading);

    const groupModified = modifiedCountsByGroup(
      Object.fromEntries(advancedValues),
      getPresetOptions(),
    )[group.id];
    if (groupModified) {
      const reset = documentRef.createElement("button");
      reset.type = "button";
      reset.className = "text-button";
      reset.textContent = t("resetGroup");
      reset.addEventListener("click", () => {
        for (const field of group.fields) {
          const presetOptions = getPresetOptions();
          if (field.key in presetOptions) advancedValues.set(field.key, presetOptions[field.key]);
          else advancedValues.delete(field.key);
        }
        renderOptionCategories();
        renderOptionPane();
        onChange();
        $("#option-category").focus({ preventScroll: true });
      });
      header.append(reset);
    }
    pane.append(header);

    const fields = visibleFields(group);
    for (const field of fields) pane.append(buildOptionRow(field, group));
    if (!fields.length) {
      const empty = documentRef.createElement("p");
      empty.className = "option-empty";
      empty.textContent = t("noOptionsMatch");
      pane.append(empty);
    }
  }

  function renderAdvancedOptions() {
    if (lifecycle.signal.aborted) return;
    renderOptionCategories();
    renderOptionPane();
  }


  $("#option-search").addEventListener("input", (event) => {
    optionSearchQuery = event.target.value.trim();
    renderOptionPane();
  }, { signal: lifecycle.signal });
  $("#option-category").addEventListener("change", (event) => {
    activeOptionGroup = event.target.value;
    $("#option-search").value = "";
    optionSearchQuery = "";
    renderOptionPane();
  }, { signal: lifecycle.signal });
  $("#show-expert").addEventListener("change", (event) => {
    showExpertOptions = event.target.checked;
    // A hidden expert group must not stay selected, or the pane would be empty.
    const group = OPTION_GROUPS.find((item) => item.id === activeOptionGroup);
    if (group?.expert && !showExpertOptions) activeOptionGroup = OPTION_GROUPS[0].id;
    renderAdvancedOptions();
  }, { signal: lifecycle.signal });
  $("#export-settings").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing || !event.target.matches('input[type="search"], input[type="text"], input[type="number"]')) return;
    event.preventDefault();
    if (event.target.type !== "search") event.target.dispatchEvent(new documentRef.defaultView.Event("change"));
  }, { signal: lifecycle.signal });

  function reset() {
    if (lifecycle.signal.aborted) return;
    advancedValues.clear();
    for (const [key, value] of Object.entries(getPresetOptions())) {
      if (key in OPTION_FIELDS) advancedValues.set(key, value);
    }
    renderAdvancedOptions();
    onChange();
  }

  return {
    render: renderAdvancedOptions,
    reset,
    overrides: () => collectRenderOptions(Object.fromEntries(advancedValues)),
    modifiedCount: () => modifiedKeys(Object.fromEntries(advancedValues), getPresetOptions()).length,
    destroy() {
      lifecycle.abort();
      $("#option-pane").replaceChildren();
    },
  };
}
