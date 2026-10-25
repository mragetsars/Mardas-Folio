/** Resolve app shortcuts without requiring a Latin text input layout. */
export function authoringShortcutKey(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.isComposing
    || event.keyCode === 229 || event.getModifierState?.("AltGraph")) return null;
  const key = String(event.key || "").toLowerCase();
  if (!key || ["dead", "process", "unidentified"].includes(key)) return null;
  // Keep logical keys for Latin layouts (including swapped QWERTZ/AZERTY
  // letters). Only non-ASCII printable keys need the physical-key fallback
  // used when, for example, Ctrl+S arrives as Persian س on Windows.
  if (/^[^\x00-\x7f]$/u.test(key)) {
    const letter = /^Key([A-Z])$/.exec(event.code || "");
    if (letter) return letter[1].toLowerCase();
    if (event.code === "Digit0") return "0";
    if (event.code === "Minus") return "-";
    if (event.code === "Equal") return "=";
    if (event.code === "Backslash") return "\\";
  }
  return key;
}
