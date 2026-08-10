/**
 * Every render option the engine accepts, described for the settings panel.
 *
 * The publishing engine takes 53 options. Listing all 53 is necessary but not
 * sufficient: a flat list of identically-weighted controls is a specification,
 * not an interface. So each option here also carries what a person needs to
 * decide it — a sentence of help, the unit it is measured in, whether it only
 * matters once something else is set, and whether it belongs in the everyday
 * set or behind "expert".
 *
 * `apps/desktop/tests/render-options.test.mjs` holds this schema against the
 * engine's own option list, so an option cannot quietly become CLI-only.
 *
 * Field vocabulary:
 *   kind        the value's type, and therefore how it is parsed on the way out
 *   widget      how it is presented; kind decides the default
 *   unit        suffix shown inside the control (mm, ms, …)
 *   helpKey     one sentence: what the option decides, not what it is called
 *   dependsOn   the option that has to be set for this one to do anything
 *   expert      hidden until the user asks for expert options
 *   preview     changing it visibly changes the previewed page
 *
 * `invert` marks options the engine states negatively (`no_mathjax`). Those are
 * shown as the positive thing the user is deciding — "render maths" — and
 * flipped on the way out.
 */

export const OPTION_GROUPS = Object.freeze([
  {
    id: "appearance",
    labelKey: "optAppearance",
    descriptionKey: "optAppearanceHelp",
    icon: "◐",
    fields: [
      { key: "style", kind: "select", helpKey: "help.style", preview: true,
        choices: ["modern", "github", "textbook", "academic"] },
      { key: "palette", kind: "select", widget: "swatches", helpKey: "help.palette", preview: true,
        choices: ["blue", "emerald", "violet", "amber", "rose", "slate", "neutral"] },
      { key: "mode", kind: "select", helpKey: "help.mode", preview: true, choices: ["light", "dark"] },
    ],
  },
  {
    id: "page",
    labelKey: "optPage",
    descriptionKey: "optPageHelp",
    icon: "▭",
    fields: [
      { key: "page_size", kind: "select", helpKey: "help.page_size", preview: true,
        choices: ["A4", "Letter", "Legal", "A3", "A5"] },
      { key: "margin_top", kind: "length", unit: "mm", placeholder: "18mm",
        helpKey: "help.margin_top", preview: true },
      { key: "margin_bottom", kind: "length", unit: "mm", placeholder: "20mm",
        helpKey: "help.margin_bottom", preview: true },
      { key: "margin_x", kind: "length", unit: "mm", placeholder: "16mm",
        helpKey: "help.margin_x", preview: true },
      { key: "no_header_footer", kind: "toggle", invert: true, helpKey: "help.no_header_footer",
        preview: true },
      { key: "h1_page_break", kind: "toggle", helpKey: "help.h1_page_break", preview: true },
    ],
  },
  {
    id: "document",
    labelKey: "optDocument",
    descriptionKey: "optDocumentHelp",
    icon: "▤",
    fields: [
      { key: "title", kind: "text", helpKey: "help.title", preview: true },
      { key: "author", kind: "text", helpKey: "help.author", preview: true },
      { key: "description", kind: "text", helpKey: "help.description", preview: true },
      { key: "document_language", kind: "text", placeholder: "auto", helpKey: "help.document_language",
        preview: true },
      { key: "document_direction", kind: "select", helpKey: "help.document_direction", preview: true,
        choices: ["auto", "ltr", "rtl"] },
      { key: "cover", kind: "toggle", helpKey: "help.cover", preview: true },
    ],
  },
  {
    id: "contents",
    labelKey: "optContents",
    descriptionKey: "optContentsHelp",
    icon: "≡",
    fields: [
      { key: "toc", kind: "toggle", helpKey: "help.toc", preview: true },
      { key: "toc_depth", kind: "number", min: 1, max: 6, helpKey: "help.toc_depth",
        dependsOn: "toc", preview: true },
      { key: "toc_page_break", kind: "toggle", helpKey: "help.toc_page_break",
        dependsOn: "toc", preview: true },
      { key: "references_enabled", kind: "toggle", helpKey: "help.references_enabled", preview: true },
      { key: "numbering_scope", kind: "select", choices: ["global", "chapter"],
        helpKey: "help.numbering_scope", dependsOn: "references_enabled", preview: true },
      { key: "list_of_figures", kind: "toggle", helpKey: "help.list_of_figures",
        dependsOn: "references_enabled", preview: true },
      { key: "list_of_tables", kind: "toggle", helpKey: "help.list_of_tables",
        dependsOn: "references_enabled", preview: true },
      { key: "list_of_equations", kind: "toggle", helpKey: "help.list_of_equations",
        dependsOn: "references_enabled", preview: true },
      { key: "list_of_listings", kind: "toggle", helpKey: "help.list_of_listings",
        dependsOn: "references_enabled", preview: true },
    ],
  },
  {
    id: "citations",
    labelKey: "optCitations",
    descriptionKey: "optCitationsHelp",
    icon: "❝",
    fields: [
      { key: "citations_enabled", kind: "toggle", helpKey: "help.citations_enabled", preview: true },
      { key: "citation_style", kind: "select", choices: ["author-date", "numeric"],
        helpKey: "help.citation_style", dependsOn: "citations_enabled", preview: true },
      { key: "bibliography_sources", kind: "list", placeholder: "refs.bib, refs.json",
        helpKey: "help.bibliography_sources", dependsOn: "citations_enabled", preview: true },
      { key: "bibliography_title", kind: "text", helpKey: "help.bibliography_title",
        dependsOn: "citations_enabled", preview: true },
      { key: "bibliography_include_uncited", kind: "toggle",
        helpKey: "help.bibliography_include_uncited", dependsOn: "citations_enabled", preview: true },
    ],
  },
  {
    id: "branding",
    labelKey: "optBranding",
    descriptionKey: "optBrandingHelp",
    icon: "◆",
    fields: [
      { key: "branding", kind: "select", choices: ["subtle", "full", "off"],
        helpKey: "help.branding", preview: true },
      { key: "brand_name", kind: "text", helpKey: "help.brand_name", preview: true },
      { key: "brand_footer", kind: "text", helpKey: "help.brand_footer", preview: true },
      { key: "brand_logo", kind: "path", helpKey: "help.brand_logo", preview: true },
      { key: "cover_logo", kind: "path", helpKey: "help.cover_logo", dependsOn: "cover",
        preview: true },
      { key: "cover_logo_enabled", kind: "toggle", helpKey: "help.cover_logo_enabled",
        dependsOn: "cover", preview: true },
    ],
  },
  {
    id: "watermark",
    labelKey: "optWatermark",
    descriptionKey: "optWatermarkHelp",
    icon: "⧉",
    fields: [
      { key: "watermark_text", kind: "text", placeholder: "DRAFT", helpKey: "help.watermark_text",
        preview: true },
      { key: "watermark_image", kind: "path", helpKey: "help.watermark_image", preview: true },
      { key: "watermark_opacity", kind: "number", widget: "slider", min: 0, max: 1, step: 0.05,
        helpKey: "help.watermark_opacity", preview: true },
      { key: "watermark_width", kind: "length", placeholder: "60%", helpKey: "help.watermark_width",
        preview: true },
    ],
  },
  {
    id: "maths",
    labelKey: "optMaths",
    descriptionKey: "optMathsHelp",
    icon: "∑",
    fields: [
      { key: "no_mathjax", kind: "toggle", invert: true, helpKey: "help.no_mathjax" },
      { key: "math_error_policy", kind: "select", choices: ["warn", "error", "ignore"],
        helpKey: "help.math_error_policy" },
    ],
  },
  {
    id: "quality",
    labelKey: "optQuality",
    descriptionKey: "optQualityHelp",
    icon: "✓",
    fields: [
      { key: "quality_profile", kind: "select", choices: ["standard", "strict-publication"],
        helpKey: "help.quality_profile" },
      { key: "font_error_policy", kind: "select", choices: ["warn", "error", "ignore"],
        helpKey: "help.font_error_policy" },
      { key: "navigation_error_policy", kind: "select", choices: ["warn", "error", "ignore"],
        helpKey: "help.navigation_error_policy" },
      { key: "required_fonts", kind: "list", placeholder: "Vazirmatn, Cascadia Mono",
        helpKey: "help.required_fonts" },
      { key: "quality_report", kind: "path", widget: "save-path", helpKey: "help.quality_report",
        expert: true },
    ],
  },
  {
    id: "security",
    labelKey: "optSecurity",
    descriptionKey: "optSecurityHelp",
    icon: "⛨",
    fields: [
      { key: "unsafe_html", kind: "toggle", helpKey: "help.unsafe_html", risky: true, preview: true },
      { key: "allow_remote_assets", kind: "toggle", helpKey: "help.allow_remote_assets",
        risky: true, preview: true },
    ],
  },
  {
    id: "engine",
    labelKey: "optEngine",
    descriptionKey: "optEngineHelp",
    icon: "⚙",
    expert: true,
    fields: [
      { key: "font_dir", kind: "path", widget: "directory", helpKey: "help.font_dir",
        expert: true, preview: true },
      { key: "chromium_path", kind: "path", helpKey: "help.chromium_path", expert: true },
      { key: "chromium_sandbox", kind: "select", choices: ["auto", "on", "off"],
        helpKey: "help.chromium_sandbox", expert: true },
      { key: "timeout_ms", kind: "number", min: 1000, max: 600000, step: 1000, unit: "ms",
        helpKey: "help.timeout_ms", expert: true },
      { key: "debug_html", kind: "path", widget: "save-path", helpKey: "help.debug_html",
        expert: true },
    ],
  },
]);

/** Flat map of key -> field descriptor. */
export const OPTION_FIELDS = Object.freeze(
  Object.fromEntries(OPTION_GROUPS.flatMap((group) => group.fields.map((f) => [f.key, f]))),
);

/** Flat map of key -> the group it belongs to. */
export const OPTION_GROUP_BY_KEY = Object.freeze(
  Object.fromEntries(
    OPTION_GROUPS.flatMap((group) => group.fields.map((field) => [field.key, group])),
  ),
);

export function optionKeys() {
  return Object.keys(OPTION_FIELDS).sort();
}

/** Parse a comma-separated list control into the array the engine expects. */
function parseList(value) {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * Turn raw control values into a render-option payload.
 *
 * Only values the user actually set are emitted. Leaving a control empty has to
 * mean "inherit", not "override with empty", or opening the panel would silently
 * wipe whatever `mardas.toml` configured.
 */
export function collectRenderOptions(values = {}) {
  const options = {};
  for (const [key, field] of Object.entries(OPTION_FIELDS)) {
    if (!(key in values)) continue;
    const raw = values[key];

    if (field.kind === "toggle") {
      if (typeof raw !== "boolean") continue;
      options[key] = field.invert ? !raw : raw;
      continue;
    }
    if (raw === undefined || raw === null || String(raw).trim() === "") continue;

    if (field.kind === "number") {
      const parsed = Number(raw);
      if (!Number.isFinite(parsed)) continue;
      options[key] = parsed;
      continue;
    }
    if (field.kind === "list") {
      const list = parseList(raw);
      if (list.length) options[key] = list;
      continue;
    }
    options[key] = String(raw).trim();
  }
  return options;
}

/** CSS lengths the engine's margin and width options accept. */
const CSS_LENGTH = /^\d+(?:\.\d+)?(?:mm|cm|in|px|pt)$/i;
const CSS_LENGTH_OR_PERCENT = /^\d+(?:\.\d+)?(?:mm|cm|in|px|pt|%)$/i;

/**
 * Why a value would be rejected, or null if it is fine.
 *
 * The engine validates these too, but only when the export runs — which is
 * after the user has stopped looking at the field they mistyped. Saying it here
 * costs one regular expression and saves a failed render.
 */
export function validateOptionValue(key, value) {
  const field = OPTION_FIELDS[key];
  if (!field) return null;
  const text = String(value ?? "").trim();
  if (!text) return null;

  if (field.kind === "length") {
    const pattern = key === "watermark_width" ? CSS_LENGTH_OR_PERCENT : CSS_LENGTH;
    return pattern.test(text) ? null : "invalidLength";
  }
  if (field.kind === "number") {
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) return "invalidNumber";
    if (field.min !== undefined && parsed < field.min) return "outOfRange";
    if (field.max !== undefined && parsed > field.max) return "outOfRange";
  }
  return null;
}

/**
 * Whether a field currently does anything.
 *
 * Watermark opacity with no watermark, contents depth with no contents: the
 * control is not wrong, it is inert, and saying so is kinder than letting
 * someone set a value that will be ignored.
 */
export function fieldIsActive(field, values = {}, defaults = {}) {
  const dependency = field?.dependsOn;
  if (!dependency) return true;
  const value = dependency in values ? values[dependency] : defaults[dependency];
  return value !== false && value !== undefined && value !== null && value !== "";
}

/** Options whose value differs from what the preset would have used. */
export function modifiedKeys(values = {}, presetOptions = {}) {
  return Object.keys(values)
    .filter((key) => key in OPTION_FIELDS)
    .filter((key) => {
      const chosen = values[key];
      const base = presetOptions[key];
      if (base === undefined) return true;
      return String(chosen) !== String(base);
    })
    .sort();
}

/** Modified-option counts per group, for the category rail's badges. */
export function modifiedCountsByGroup(values = {}, presetOptions = {}) {
  const counts = {};
  for (const key of modifiedKeys(values, presetOptions)) {
    const group = OPTION_GROUP_BY_KEY[key];
    if (!group) continue;
    counts[group.id] = (counts[group.id] || 0) + 1;
  }
  return counts;
}

/**
 * Find options by free text.
 *
 * Search covers the option's own key as well as its translated label and help,
 * because someone who knows the engine looks for `margin_x` and someone who
 * does not looks for "side margins".
 */
export function searchOptions(query, translate = (key) => key) {
  const needle = String(query || "").trim().toLocaleLowerCase();
  if (!needle) return null;
  const matches = [];
  for (const group of OPTION_GROUPS) {
    for (const field of group.fields) {
      const haystack = [
        field.key,
        field.key.replaceAll("_", " "),
        translate(`opt.${field.key}`),
        field.helpKey ? translate(field.helpKey) : "",
        translate(group.labelKey),
      ]
        .join(" ")
        .toLocaleLowerCase();
      if (haystack.includes(needle)) matches.push({ group, field });
    }
  }
  return matches;
}
