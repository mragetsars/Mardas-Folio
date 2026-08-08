export const SUPPORTED_EXPORT_STYLES = Object.freeze([
  "modern",
  "github",
  "textbook",
  "academic",
]);

export const SUPPORTED_EXPORT_PALETTES = Object.freeze([
  "blue",
  "emerald",
  "violet",
  "amber",
  "rose",
  "slate",
  "neutral",
]);

export const SUPPORTED_EXPORT_MODES = Object.freeze(["light", "dark"]);

function createPreset(id, titleKey, descriptionKey, options) {
  return Object.freeze({
    id,
    titleKey,
    descriptionKey,
    options: Object.freeze(options),
  });
}

export const PRESETS = Object.freeze({
  general: createPreset("general", "presetGeneral", "presetGeneralHelp", {
    style: "modern",
    palette: "blue",
    mode: "light",
    page_size: "A4",
    toc: true,
    quality_profile: "standard",
    document_language: "auto",
  }),
  academic: createPreset("academic", "presetAcademic", "presetAcademicHelp", {
    style: "academic",
    palette: "blue",
    mode: "light",
    page_size: "A4",
    toc: true,
    quality_profile: "strict-publication",
    document_language: "auto",
    references_enabled: true,
    citations_enabled: true,
  }),
  technical: createPreset("technical", "presetTechnical", "presetTechnicalHelp", {
    style: "modern",
    palette: "emerald",
    mode: "light",
    page_size: "A4",
    toc: true,
    quality_profile: "strict-publication",
    document_language: "auto",
  }),
  minimal: createPreset("minimal", "presetMinimal", "presetMinimalHelp", {
    // The quiet preset is a neutral, no-TOC variant of the canonical modern
    // style; "minimal" is a preset name, not a renderer style enum.
    style: "modern",
    palette: "neutral",
    mode: "light",
    page_size: "A4",
    toc: false,
    quality_profile: "standard",
    document_language: "auto",
  }),
});

export function presetById(id) {
  return PRESETS[id] ?? PRESETS.general;
}

export function mergePresetOptions(id, overrides = {}) {
  return { ...presetById(id).options, ...overrides };
}
