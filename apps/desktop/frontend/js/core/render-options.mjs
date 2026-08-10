/**
 * Every render option the engine accepts, described for the settings panel.
 *
 * The publishing engine takes 53 options; before this the interface sent nine
 * and the rest were reachable only by hand-editing `mardas.toml` or dropping to
 * the CLI. The panel is generated from this schema so adding an option here is
 * the only step needed to surface it, and
 * `apps/desktop/tests/render-options.test.mjs` holds the schema against the
 * engine's own list so an option cannot quietly become CLI-only again.
 *
 * `invert` marks the options the engine states negatively (`no_mathjax`). Those
 * are shown as the positive thing the user is deciding — "render maths" — and
 * flipped on the way out.
 */

export const OPTION_GROUPS = Object.freeze([
  {
    id: "appearance",
    labelKey: "optAppearance",
    fields: [
      { key: "style", kind: "select", choices: ["modern", "github", "textbook", "academic"] },
      { key: "palette", kind: "select",
        choices: ["blue", "emerald", "violet", "amber", "rose", "slate", "neutral"] },
      { key: "mode", kind: "select", choices: ["light", "dark"] },
      { key: "page_size", kind: "select", choices: ["A4", "Letter", "Legal", "A3", "A5"] },
    ],
  },
  {
    id: "document",
    labelKey: "optDocument",
    fields: [
      { key: "title", kind: "text" },
      { key: "author", kind: "text" },
      { key: "description", kind: "text" },
      { key: "document_language", kind: "text", placeholder: "auto" },
      { key: "document_direction", kind: "select", choices: ["auto", "ltr", "rtl"] },
    ],
  },
  {
    id: "layout",
    labelKey: "optLayout",
    fields: [
      { key: "toc", kind: "toggle" },
      { key: "toc_depth", kind: "number", min: 1, max: 6 },
      { key: "toc_page_break", kind: "toggle" },
      { key: "h1_page_break", kind: "toggle" },
      { key: "cover", kind: "toggle" },
      { key: "no_header_footer", kind: "toggle", invert: true },
      { key: "no_mathjax", kind: "toggle", invert: true },
      { key: "margin_top", kind: "length", placeholder: "18mm" },
      { key: "margin_bottom", kind: "length", placeholder: "20mm" },
      { key: "margin_x", kind: "length", placeholder: "16mm" },
    ],
  },
  {
    id: "references",
    labelKey: "optReferences",
    fields: [
      { key: "references_enabled", kind: "toggle" },
      { key: "numbering_scope", kind: "select", choices: ["global", "chapter"] },
      { key: "list_of_figures", kind: "toggle" },
      { key: "list_of_tables", kind: "toggle" },
      { key: "list_of_equations", kind: "toggle" },
      { key: "list_of_listings", kind: "toggle" },
    ],
  },
  {
    id: "citations",
    labelKey: "optCitations",
    fields: [
      { key: "citations_enabled", kind: "toggle" },
      { key: "citation_style", kind: "select", choices: ["author-date", "numeric"] },
      { key: "bibliography_title", kind: "text" },
      { key: "bibliography_sources", kind: "list", placeholder: "refs.bib, refs.json" },
      { key: "bibliography_include_uncited", kind: "toggle" },
    ],
  },
  {
    id: "branding",
    labelKey: "optBranding",
    fields: [
      { key: "branding", kind: "select", choices: ["subtle", "full", "off"] },
      { key: "brand_name", kind: "text" },
      { key: "brand_footer", kind: "text" },
      { key: "brand_logo", kind: "path" },
      { key: "cover_logo", kind: "path" },
      { key: "cover_logo_enabled", kind: "toggle" },
    ],
  },
  {
    id: "watermark",
    labelKey: "optWatermark",
    fields: [
      { key: "watermark_text", kind: "text", placeholder: "DRAFT" },
      { key: "watermark_image", kind: "path" },
      { key: "watermark_opacity", kind: "number", min: 0, max: 1, step: 0.05 },
      { key: "watermark_width", kind: "length", placeholder: "60%" },
    ],
  },
  {
    id: "quality",
    labelKey: "optQuality",
    fields: [
      { key: "quality_profile", kind: "select", choices: ["standard", "strict-publication"] },
      { key: "math_error_policy", kind: "select", choices: ["warn", "error", "ignore"] },
      { key: "font_error_policy", kind: "select", choices: ["warn", "error", "ignore"] },
      { key: "navigation_error_policy", kind: "select", choices: ["warn", "error", "ignore"] },
      { key: "required_fonts", kind: "list", placeholder: "Vazirmatn, Cascadia Mono" },
      { key: "quality_report", kind: "path" },
    ],
  },
  {
    id: "security",
    labelKey: "optSecurity",
    fields: [
      { key: "unsafe_html", kind: "toggle" },
      { key: "allow_remote_assets", kind: "toggle" },
    ],
  },
  {
    id: "engine",
    labelKey: "optEngine",
    fields: [
      { key: "font_dir", kind: "path" },
      { key: "chromium_path", kind: "path" },
      { key: "chromium_sandbox", kind: "select", choices: ["auto", "on", "off"] },
      { key: "timeout_ms", kind: "number", min: 1000, max: 600000, step: 1000 },
      { key: "debug_html", kind: "path" },
    ],
  },
]);

/** Flat map of key -> field descriptor. */
export const OPTION_FIELDS = Object.freeze(
  Object.fromEntries(OPTION_GROUPS.flatMap((group) => group.fields.map((f) => [f.key, f]))),
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
