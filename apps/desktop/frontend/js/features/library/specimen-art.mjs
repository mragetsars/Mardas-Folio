// Artwork geometry for the physical specimens and deck icons.
const artCache = new Map();
export function coverPattern(name) {
  if (name === "plain") return "";
  if (artCache.has(name)) return artCache.get(name);
  let shapes = "";
  if (name === "terrain") {
    shapes = '<circle cx="164" cy="31" r="18" fill="#f4d89d"/>';
    const terrain = [];
    for (let j = 0; j < 31; j++) {
      const points = [];
      for (let x = -4; x <= 244; x += 3) {
        const h =
          66 +
          j * 3.25 +
          7 * Math.sin(x * 0.027 + j * 0.17) +
          3.1 * Math.sin(x * 0.071 - j * 0.091) -
          26 * Math.exp(-(((x - 72 - j * 1.5) / 28) ** 2)) -
          20 * Math.exp(-(((x - 125 + j * 0.8) / 23) ** 2)) +
          2.3 * Math.sin(x * 0.19 + j * 0.28) +
          1.7 * Math.sin(x * 0.36 - j * 0.19);
        points.push(`${x},${h.toFixed(1)}`);
      }
      const ridge = "M" + points.join(" L");
      terrain.push(
        `<path d="${ridge} V154 H-4Z" fill="var(--cover)"/><path d="${ridge}" fill="none" stroke="#ecebc9" stroke-width="${j % 5 === 0 ? 1.25 : 0.8}" opacity="${(0.45 + j * 0.012).toFixed(2)}"/>`,
      );
    }
    shapes += terrain.join("");
  } else if (name === "wave") {
    const paths = [];
    for (let i = -12; i < 37; i++) {
      const y = i * 5;
      paths.push(
        `<path d="M-15 ${y + 8} C 38 ${y - 21}, 64 ${y + 78}, 122 ${y + 22} S 193 ${y - 13}, 254 ${y + 10}"/>`,
      );
    }
    shapes = `<g fill="none" stroke="currentColor" stroke-width="1.35" opacity=".86">${paths.join("")}</g>`;
  } else if (name === "orbit") {
    const rings = [];
    for (let i = 1; i < 21; i++)
      rings.push(
        `<ellipse cx="${70 + i * 1.7}" cy="${65 + i * 0.6}" rx="${i * 7.3}" ry="${i * 4.2}" transform="rotate(-31 110 65)"/>`,
      );
    shapes = `<g fill="none" stroke="currentColor" stroke-width="1.55" opacity=".9">${rings.join("")}</g>`;
  } else if (name === "fold") {
    shapes =
      '<path d="m0 0 81 0 56 146H62z" fill="currentColor" opacity=".62"/><path d="m81 0 58 0-2 146z" fill="#101015" opacity=".42"/><path d="m140 0 100 0-103 146z" fill="currentColor" opacity=".85"/><path d="m240 0-46 146h-57z" fill="#15151a" opacity=".65"/>';
  }
  const result = `<svg viewBox="0 0 240 146" preserveAspectRatio="xMidYMid slice" aria-hidden="true">${shapes}</svg>`;
  artCache.set(name, result);
  return result;
}
export function paperClipArt(front) {
  // Both arms meet at (3, 7), where the wire comes around the sheet edge.
  const wire = front
    ? "M3 7C3 4.4 4.9 2.5 7.2 2.5S11.4 4.4 11.4 7V22.4C11.4 27.8 4.7 27.8 4.7 22.4V12.1"
    : "M3 7V24.5C3 31.2 13 31.2 13 24.5V11.8";
  return `<svg viewBox="0 0 15 32" aria-hidden="true"><path d="${wire}" fill="none" stroke="#545c62" stroke-width="1.85" stroke-linecap="round"/><path d="${wire}" fill="none" stroke="#e1e5e8" stroke-width=".95" stroke-linecap="round" transform="translate(-.18,-.21)"/></svg>`;
}
export function avatarArt(gender) {
  const female = gender !== "man";
  const hair = female
    ? '<path d="M13 31c-1-15 7-23 18-23 13 0 19 10 17 24l3 23-39-1z" fill="#343f3c"/>'
    : '<path d="M16 27c-1-12 4-20 16-20 9 0 17 5 15 20l-6 12-21-1z" fill="#35423c"/>';
  const fringe = female
    ? '<path d="M17 29c-1-12 4-19 14-19 8 0 15 6 15 18-5-3-10-7-12-11-4 7-9 10-17 12z" fill="#323e38"/>'
    : '<path d="M17 25c0-12 5-17 16-17 7 0 12 4 14 10l-4 10-3-11c-8 5-15 6-23 8z" fill="#303c35"/>';
  return `<svg viewBox="0 0 62 76" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><rect width="62" height="76" fill="${gender === "neutral" ? "#d9e2df" : female ? "#d5e4da" : "#d6e1ed"}"/><circle cx="15" cy="13" r="32" fill="#fff" opacity=".23"/>${hair}<path d="M3 79c1-16 7-23 20-27h15c13 3 20 12 23 27z" fill="${female ? "#435c50" : "#465d70"}"/><path d="M25 43h13l1 11-8 8-9-8z" fill="#bd8e70"/><path d="M18 26c0-9 5-14 13-14 10 0 15 6 14 17l-1 6c-1 9-8 16-13 16s-12-6-13-16z" fill="#dab59a"/>${fringe}<path d="M22 31q3-1.5 5 0m8 0q3-1.5 5 0m-9 2-1.5 5 2 .4m-4 4q3 2 6 0" fill="none" stroke="#765d50" stroke-width="1.1" stroke-linecap="round"/><circle cx="25" cy="33" r=".8" fill="#3d3933"/><circle cx="37" cy="33" r=".8" fill="#3d3933"/><path d="m22 53 9 9-5 4-8-12m21-1-8 9 6 4 7-11" fill="#ffffff38"/></svg>`;
}
export const binderArt = `<svg viewBox="0 0 36 35" aria-hidden="true"><path d="M9 22 7 8C6 1 15 1 15 7l-1 12m8 0-1-12c0-6 9-6 8 1l-2 14" fill="none" stroke="#676b6d" stroke-width="2.7"/><path d="M9 22 7 8C6 1 15 1 15 7m7 12-1-12c0-6 9-6 8 1l-2 14" fill="none" stroke="#e5e7e5" stroke-width="1"/><path d="M2 19h32l-3 13H5z" fill="#292d2e" stroke="#16191a"/><path d="M3 21h30M6 30h24" stroke="#575c5b"/><path d="M1 18.7h34" stroke="#a1a5a3" stroke-width="2" stroke-linecap="round"/></svg>`;
export const duoArt = `<svg viewBox="0 0 36 57" aria-hidden="true"><circle cx="18" cy="18" r="18" fill="#43ddbe"/><circle cx="18" cy="39" r="18" fill="#ed4f56"/><path d="M3.38 28.5a18 18 0 0 0 29.24 0 18 18 0 0 0-29.24 0Z" fill="#096bff"/></svg>`;
export const smallIcons = {
  triangle: '<path d="m12 3 10 18H2z" fill="currentColor" stroke="none"></path>',
  spark:
    '<path d="m12 1.5 2.4 7.7 7.1 2.8-7.1 2.8-2.4 7.7-2.4-7.7-7.1-2.8 7.1-2.8z" fill="currentColor" stroke="none"></path>',
  leaf: '<path d="M4.5 17.5C2 9 9 3 20 3c0 11-6 18-14 15m-2 3L15 10" stroke-width="2.2"></path>',
  orbit:
    '<circle cx="12" cy="12" r="7"></circle><ellipse cx="12" cy="12" rx="11" ry="3.4" transform="rotate(-35 12 12)"></ellipse>',
  trash: '<path d="M4 6h16M9 6V3.5h6V6m-9 0 1 14h10l1-14M10 9v7m4-7v7"></path>',
  note: '<path d="M4 4h16v11l-5 5H4zM15 20v-5h5M7.5 9h8m-8 3h5"></path>',
  resume:
    '<rect x="4" y="3" width="16" height="18" rx="1.5"></rect><circle cx="12" cy="8.5" r="2"></circle><path d="M8.2 14a4.3 4.3 0 0 1 7.6 0M8 17.5h8"></path>',
  article:
    '<rect x="6" y="3" width="14" height="18" rx="1.6"></rect><path d="M3 6h5M3 10h5M3 14h5M3 18h5m3-11h5m-5 4h5m-5 4h3"></path>',
};
