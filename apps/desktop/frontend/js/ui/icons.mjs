/**
 * An icon from the sprite in `index.html`.
 *
 * `<use>` rather than an inline copy of the path: the sprite is already in the
 * document, and duplicating a symbol per button is how two drawings of the
 * same idea drift apart.
 */
export function spriteIcon(name, documentRef = globalThis.document) {
  const svg = documentRef.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ui-icon");
  svg.setAttribute("aria-hidden", "true");
  const use = documentRef.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.append(use);
  return svg;
}
