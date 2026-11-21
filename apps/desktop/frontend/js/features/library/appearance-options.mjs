export const choices = {
  variant: ["band", "full"],
  texture: ["smooth", "linen", "paper", "leather", "twill"],
  pattern: ["plain", "fold", "wave", "orbit"],
  mark: ["auto", "duo", "triangle", "none"],
  fastener: ["staple", "clip", "binder"],
  material: ["sticky", "kraft", "cotton"],
  binding: ["strip", "wire"],
  avatar: ["neutral", "woman", "man"],
  privacy: ["visible", "hidden"],
};

export function restoredAppearance(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result = {};
  for (const [key, v] of Object.entries(value)) {
    if (typeof v !== "string") continue;
    if (
      choices[key]?.includes?.(v) ||
      (key === "color" && /^#[0-9a-f]{6}$/i.test(v)) ||
      (key === "label" && v.length <= 180) ||
      (["picture", "logo"].includes(key) &&
        v.length <= 98304 &&
        /^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/u.test(v))
    )
      result[key] = v;
  }
  return result;
}
