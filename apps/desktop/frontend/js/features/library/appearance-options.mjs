export const choices = {
  variant: ["full", "band"],
  texture: ["smooth", "linen", "paper", "leather", "twill"],
  pattern: ["plain", "wave", "orbit", "terrain", "fold"],
  mark: ["auto", "duo", "triangle", "brand", "spark", "leaf", "orbit", "none"],
  fastener: ["staple", "clip", "binder"],
  sheets: Array.from({ length: 11 }, (_, index) => String(index + 2)),
  material: ["kraft", "sticky", "cotton"],
  ruling: ["auto", "plain", "lined", "grid", "dot"],
  tape: ["auto", "none", "masking", "washi"],
  binding: ["strip", "wire"],
  avatar: ["neutral", "woman", "man"],
  privacy: ["visible", "hidden"],
  pictureSource: ["preset", "uploaded"],
  logoSource: ["preset", "uploaded"],
};

export const paperColors = { kraft: "#e8d6a6", sticky: "#f6df77", cotton: "#f6f4ec" };
export const palette = [
  "#7bbfc0",
  "#9f2830",
  "#f3c947",
  "#2855ce",
  "#7755a8",
  "#24564c",
  "#bd463c",
  "#e9b648",
  "#27292d",
  "#f7f6f0",
];
export const notePalette = [
  paperColors.kraft,
  paperColors.cotton,
  paperColors.sticky,
  "#f3b1b6",
  "#a9d7b6",
  "#aad4e8",
  "#c9b4e4",
  "#f6c294",
];

const byType = {
  book: { color: "#7bbfc0", variant: "band", texture: "linen", pattern: "plain", mark: "auto" },
  document: { color: "#537c6a", fastener: "staple", sheets: "4", mark: "brand" },
  note: { color: paperColors.sticky, material: "sticky", ruling: "auto", tape: "auto" },
  resume: { color: "#8296a8", avatar: "woman" },
  article: { color: "#24564c", binding: "strip", pattern: "terrain" },
};
export function defaults(type) {
  return { ...byType[type], privacy: "visible" };
}
export function paperKey(material) {
  return material + "Color";
}
export function isColor(value) {
  return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
}
export function noteColor(a) {
  const color = a[paperKey(a.material)] || (a.material === "sticky" ? a.color : undefined);
  return isColor(color) ? color : paperColors[a.material];
}
export function chartValues(value = "") {
  return value
    .replace(/[۰-۹٠-٩]/gu, (v) => String(v.charCodeAt(0) - (v >= "۰" ? 1776 : 1632)))
    .split(/[،,;؛\s]+/u)
    .filter(Boolean)
    .map(Number)
    .filter(Number.isFinite)
    .map((v) => Math.max(0, Math.min(v, 100)))
    .slice(0, 28);
}

export const FONT_SOURCE_LIMIT = 262144;
export function handwritingSource(value) {
  return (
    typeof value === "string" &&
    value.length <= FONT_SOURCE_LIMIT &&
    /^data:font\/(?:woff2?|ttf|otf);base64,[A-Za-z0-9+/]+={0,2}$/u.test(value)
  );
}
export function restoredAppearance(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result = {};
  for (const [key, v] of Object.entries(value)) {
    if (typeof v !== "string") continue;
    if (
      choices[key]?.includes?.(v) ||
      (["color", ...Object.keys(paperColors).map(paperKey)].includes(key) && isColor(v)) ||
      (["label", "chart", "letterhead"].includes(key) && v.length <= 180 && !v.includes("\0")) ||
      (key === "handFont" && handwritingSource(v)) ||
      (["picture", "logo"].includes(key) &&
        v.length <= 98304 &&
        /^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/u.test(v))
    )
      result[key] = v;
  }
  return result;
}
