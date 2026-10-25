/** Resolve app shortcuts without requiring a Latin text input layout. */
export function authoringShortcutKey(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.isComposing
    || event.keyCode === 229 || event.getModifierState?.("AltGraph")) return null;
  const key = String(event.key || "").toLowerCase();
  if (!key || ["dead", "process", "unidentified"].includes(key)) return null;
  // Keep logical alphabetic keys for Latin layouts (including swapped
  // QWERTZ/AZERTY letters). Other single printable keys can belong to a letter
  // key in another layout: Persian Ctrl+S is س and Ctrl+Shift+P is backslash.
  if (/^.$/u.test(key) && !/^[a-z]$/.test(key)) {
    const letter = /^Key([A-Z])$/.exec(event.code || "");
    if (letter) return letter[1].toLowerCase();
    if ((event.code == null || event.code === "") && Number.isInteger(event.keyCode)
      && event.keyCode >= 65 && event.keyCode <= 90) {
      return String.fromCharCode(event.keyCode + 32);
    }
  }
  if (/^[^\x00-\x7f]$/u.test(key)) {
    if (event.code === "Digit0") return "0";
    if (event.code === "Minus") return "-";
    if (event.code === "Equal") return "=";
    if (event.code === "Backslash") return "\\";
    // Some native Windows input paths supply the legacy virtual key but no
    // `code`. Do not override an explicit code or infer letters from arbitrary
    // values; the composition/AltGraph guards above still apply.
    if ((event.code == null || event.code === "") && Number.isInteger(event.keyCode)) {
      if (event.keyCode === 48) return "0";
      if (event.keyCode === 189) return "-";
      if (event.keyCode === 187) return "=";
      if (event.keyCode === 220) return "\\";
    }
  }
  return key;
}
