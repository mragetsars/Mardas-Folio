import { createTranslator } from "../../core/i18n.mjs";
import { chartValues, defaults, handwritingSource, noteColor } from "./appearance-options.mjs";
import {
  avatarArt,
  binderArt,
  coverPattern,
  duoArt,
  paperClipArt,
  smallIcons,
} from "./specimen-art.mjs";

export function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

const part = (name, text) => element("span", "folio-" + name, text);
const ns = "http://www.w3.org/2000/svg";
export function libraryIcon(name) {
  const vector = document.createElementNS(ns, "svg");
  vector.setAttribute("class", "library-icon");
  vector.setAttribute("viewBox", "0 0 24 24");
  vector.setAttribute("aria-hidden", "true");
  if (Object.hasOwn(smallIcons, name)) vector.innerHTML = smallIcons[name];
  else {
    const use = document.createElementNS(ns, "use");
    use.setAttribute("href", "#icon-" + (name === "edit" ? "pencil" : name));
    vector.append(use);
  }
  return vector;
}

function illustration(name, markup) {
  const node = part(name);
  node.innerHTML = markup;
  return node;
}

function picture(src) {
  if (typeof src !== "string" || !/^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/u.test(src))
    return null;
  const image = element("img");
  image.alt = "";
  image.src = src;
  image.draggable = false;
  return image;
}

function directed(node, text) {
  const letter = String(text || "").match(/\p{L}/u)?.[0] || "";
  node.dir =
    /[\p{Script=Arabic}\p{Script=Hebrew}\p{Script=Syriac}\p{Script=Thaana}\p{Script=Nko}\p{Script=Adlam}]/u.test(
      letter,
    )
      ? "rtl"
      : "ltr";
  return node;
}
function textPart(name, value) {
  const node = part(name, value);
  node.dir = "auto";
  return node;
}
function inkOn(color) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const value = parseInt(color.slice(i, i + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return r * 0.2126 + g * 0.7152 + b * 0.0722 > 0.179 ? "#141417" : "#fff";
}
function mark(a, fallback, name) {
  const photo = a.logoSource === "preset" ? null : picture(a.logo);
  const node = part(name);
  if (photo) node.append(photo);
  else {
    const shape = a.mark === "auto" ? fallback : a.mark;
    if (shape === "none") return document.createDocumentFragment();
    if (shape === "duo") {
      node.classList.add("folio-duo");
      node.innerHTML = duoArt;
    } else {
      node.append(libraryIcon(shape === "brand" ? "branding" : shape));
    }
  }
  return node;
}
function artwork(a, photo) {
  const node = part("cover-art");
  if (photo) node.append(photo);
  else node.innerHTML = coverPattern(a.pattern);
  return node;
}
function volume(front) {
  const node = part("volume");
  node.append(part("volume-back"), part("volume-pages"), front);
  return node;
}
function book(shell, a, item, photo) {
  const title = textPart("cover-title", item.title);
  const copy = directed(part("cover-copy"), item.title);
  copy.append(title, mark(a, a.variant === "full" ? "duo" : "triangle", "cover-mark"));
  shell.dataset.variant = a.variant;
  shell.dataset.texture = a.texture;
  shell.toggleAttribute("data-photo", Boolean(photo));
  shell.toggleAttribute("data-patterned", a.pattern !== "plain" && !photo);
  if (photo) shell.style.setProperty("--on-cover", "#fff");
  const front = part("volume-front");
  front.append(artwork(a, photo), copy, part("cover-skin"), part("hinge"));
  shell.append(volume(front));
}
function report(shell, a, item) {
  const pages = Number(a.sheets);
  const freedom = { staple: 1, clip: 0.64, binder: 0.47 }[a.fastener];
  shell.dataset.fastener = a.fastener;
  if (a.fastener === "clip") shell.append(illustration("paperclip-back", paperClipArt(false)));
  for (let i = pages - 1; i >= 1; i--) {
    const progress = i / (pages - 1);
    const sign = i % 2 ? 1 : -1;
    const leaf = part("a4-leaf");
    leaf.style.setProperty("--rest", (sign * (0.4 + progress * 1.6)).toFixed(2) + "deg");
    leaf.style.setProperty("--swing", (sign * freedom * (1.9 + progress * 4.8)).toFixed(2) + "deg");
    shell.append(leaf);
  }
  const front = directed(part("report-front"), item.title);
  const masthead = part("report-mast");
  masthead.append(
    mark(a, "brand", "report-logo"),
    textPart("clamp", a.letterhead || item.organization),
  );
  const title = textPart("report-heading", item.title);
  title.classList.add("folio-clamp");
  const body = textPart("report-body", item.detail);
  body.classList.add("folio-mini-copy", "folio-clamp");
  front.append(masthead, title, body);
  const chart = chartValues(a.chart);
  if (chart.length) {
    const bars = part("report-bars");
    for (const value of chart) {
      const bar = element("i");
      bar.style.setProperty("--height", value + "%");
      bars.append(bar);
    }
    front.append(bars);
  }
  const number = new Intl.NumberFormat(front.dir === "rtl" ? "fa-IR" : "en", {
    useGrouping: false,
  });
  const folio = part("report-folio");
  folio.append(textPart("page-count", number.format(1) + " / " + number.format(pages)));
  front.append(folio);
  shell.append(front);
  if (a.fastener === "clip") shell.append(illustration("paperclip", paperClipArt(true)));
  else if (a.fastener === "binder") shell.append(illustration("binder-clip", binderArt));
  else shell.append(part("staple"));
}
const handFonts = new Map();
export async function useHandwriting(data) {
  if (!handwritingSource(data) || !globalThis.FontFace) return "";
  if (!handFonts.has(data)) {
    const family = "FolioHand" + (handFonts.size + 1);
    const bytes = Uint8Array.from(atob(data.slice(data.indexOf(",") + 1)), (char) =>
      char.charCodeAt(0),
    );
    const ready = new FontFace(family, bytes).load().then((font) => {
      document.fonts.add(font);
      return family;
    });
    handFonts.set(data, ready);
  }
  return handFonts.get(data);
}
function looseSheet(name, title) {
  const loose = part("loose");
  const face = directed(part("loose-face"), title);
  face.classList.add("folio-" + name);
  loose.append(face);
  return { loose, face };
}
function note(shell, a, item) {
  const paper = noteColor(a);
  shell.dataset.material = a.material;
  shell.dataset.ruling =
    a.ruling === "auto" ? { kraft: "lined", sticky: "plain", cotton: "dot" }[a.material] : a.ruling;
  shell.style.setProperty("--paper", paper);
  shell.style.setProperty("--paper-ink", inkOn(paper));
  if (a.handFont)
    void useHandwriting(a.handFont)
      .then((family) => {
        if (family) shell.style.setProperty("--custom-hand", family);
      })
      .catch(() => {});
  const { loose, face } = looseSheet("note-stock", item.title);
  const title = textPart("note-title", item.title);
  const body = textPart("note-body", item.detail);
  for (const node of [title, body]) node.classList.add("folio-hand", "folio-clamp");
  face.append(title, body, part("dogear"));
  const tape = a.tape === "auto" ? (a.material === "kraft" ? "masking" : "none") : a.tape;
  if (a.material !== "cotton" && tape !== "none") {
    const strip = part("note-tape");
    strip.dataset.tape = tape;
    loose.append(strip);
  }
  shell.append(loose);
  if (a.material === "cotton") shell.append(part("note-pin"));
}
function resume(shell, a, item, photo) {
  const { loose, face } = looseSheet("resume-stock", item.title);
  const { t } = createTranslator(face.dir === "rtl" ? "fa" : "en");
  const header = part("resume-header");
  const portrait = photo ? part("portrait") : illustration("portrait", avatarArt(a.avatar));
  if (photo) portrait.append(photo);
  const heading = element("span");
  const name = textPart("resume-name", item.title);
  name.classList.add("folio-clamp");
  const role = textPart("resume-role", item.detail);
  role.classList.add("folio-clamp");
  heading.append(name, role);
  header.append(portrait, heading);
  face.append(header);
  if (item.summary) {
    const summary = textPart("resume-summary", item.summary);
    summary.classList.add("folio-mini-copy", "folio-clamp");
    face.append(part("section-name", t("shelfProfile")), summary);
  }
  if (item.skills) {
    const skills = part("skill-items");
    for (const name of item.skills
      .split(/[,،;؛]+/u)
      .map((value) => value.trim())
      .filter(Boolean))
      skills.append(textPart("skill", name));
    face.append(part("section-name", t("shelfSkills")), skills);
  }
  const folio = part("resume-folio");
  folio.append(element("span", "", "CV"));
  face.append(folio, part("dogear"));
  shell.append(loose);
}
function article(shell, a, item, photo) {
  const front = part("volume-front");
  front.classList.add("folio-article-front");
  const copy = directed(part("article-copy"), item.title);
  const title = textPart("article-title", item.title);
  const byline = textPart("article-byline", item.author);
  title.classList.add("folio-clamp");
  byline.classList.add("folio-clamp");
  if (item.detail) {
    const kicker = textPart("article-kicker", item.detail);
    kicker.classList.add("folio-clamp");
    copy.append(kicker);
  }
  copy.append(title, byline);
  const binding = part(a.binding === "wire" ? "wire-binding" : "binding-strip");
  if (a.binding === "wire") {
    for (let i = 0; i < 14; i++) binding.append(part("wire-loop"));
  }
  front.append(artwork(a, photo), copy, binding);
  shell.append(volume(front));
}

export function shelfObject(item, t) {
  const a = { ...defaults(item.type), ...item.appearance };
  const shell = part("object");
  shell.classList.add("folio-" + item.type + "-scene");
  shell.setAttribute("aria-hidden", "true");
  const masked = a.privacy === "hidden";
  const title = masked ? t("shelfPrivate") : a.label || item.title || t("shelf" + item.type);
  const text = masked ? { title } : { ...item, title };
  const photo = masked || a.pictureSource === "preset" ? null : picture(a.picture);
  const color = /^#[0-9a-f]{6}$/i.test(a.color) ? a.color : defaults(item.type).color;
  shell.style.setProperty("--cover", color);
  shell.style.setProperty("--on-cover", inkOn(color));
  shell.style.setProperty("--art-ink", inkOn(color));
  if (masked) {
    delete a.logo;
    a.chart = "";
    a.letterhead = "";
  }
  if (item.type === "book") book(shell, a, text, photo);
  if (item.type === "document") report(shell, a, text);
  if (item.type === "note") note(shell, a, text);
  if (item.type === "resume") resume(shell, a, text, photo);
  if (item.type === "article") article(shell, a, text, photo);
  return shell;
}
