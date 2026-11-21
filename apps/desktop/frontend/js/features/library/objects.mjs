const BASE_COLOR = {
  book: "#77b3b3",
  document: "#597d6f",
  note: "#f3d986",
  resume: "#8296a8",
  article: "#346558",
};

export function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}
export function defaults(type) {
  return {
    color: BASE_COLOR[type],
    variant: "band",
    texture: "linen",
    pattern: type === "article" ? "wave" : "plain",
    fastener: "staple",
    material: "sticky",
    binding: "strip",
    mark: "auto",
    avatar: "neutral",
    privacy: "visible",
  };
}
const part = (name, text) => element("span", "folio-" + name, text);
function picture(src) {
  if (typeof src !== "string" || !/^data:image\/jpeg;base64,[A-Za-z0-9+/]+=*$/u.test(src))
    return null;
  const im = element("img");
  im.alt = "";
  im.src = src;
  im.draggable = false;
  return im;
}
function svg(view, paths) {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  s.setAttribute("viewBox", view);
  for (const [d, color, width] of paths) {
    const p = document.createElementNS(ns, "path");
    p.setAttribute("d", d);
    p.setAttribute("fill", "none");
    p.setAttribute("stroke", color);
    p.setAttribute("stroke-width", width);
    p.setAttribute("stroke-linecap", "round");
    s.append(p);
  }
  return s;
}
function clip(rear) {
  const n = part(rear ? "clip-back" : "clip-front");
  const path = rear ? "M8 18V8a5 5 0 0 1 10 0v19" : "M18 8v22a8 8 0 0 1-16 0V9a4 4 0 0 1 8 0v18";
  n.append(
    svg("0 0 20 40", [
      [path, "#555e61", "3"],
      [path, "#dce1e3", "1.35"],
    ]),
  );
  return n;
}
function textPart(name, value) {
  const n = part(name, value);
  n.dir = "auto";
  return n;
}
function iconMark(appearance, full) {
  const mark = part("mark");
  const img = picture(appearance.logo);
  if (img) mark.append(img);
  else
    mark.dataset.shape = appearance.mark === "auto" ? (full ? "duo" : "triangle") : appearance.mark;
  return mark;
}
export function shelfObject(item, t) {
  const a = { ...defaults(item.type), ...item.appearance };
  const shell = part("object"),
    front = part("front");
  const masked = a.privacy === "hidden";
  const title = textPart(
    "object-title",
    masked ? t("shelfPrivate") : a.label || item.title || t("shelf" + item.type),
  );
  const detail = textPart("object-detail", masked ? "" : item.detail);
  const pic = masked ? null : picture(a.picture);
  shell.dataset.type = item.type;
  for (const key of ["variant", "texture", "pattern", "fastener", "material", "binding", "avatar"])
    shell.dataset[key] = a[key];
  shell.style.setProperty(
    "--cover",
    /^#[0-9a-f]{6}$/i.test(a.color) ? a.color : BASE_COLOR[item.type],
  );
  const color = /^#[0-9a-f]{6}$/i.test(a.color) ? a.color : BASE_COLOR[item.type];
  const rgb = [1, 3, 5]
    .map((i) => parseInt(color.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  shell.style.setProperty(
    "--cover-ink",
    0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] > 0.18 ? "#191919" : "#fff",
  );
  shell.setAttribute("aria-hidden", "true");
  if (item.type === "book" || item.type === "article") {
    const art = part("cover-art"),
      copy = part("cover-copy"),
      volume = part("volume");
    if (pic) {
      art.append(pic);
      shell.dataset.photo = "true";
    }
    copy.append(title);
    if (item.type === "article") {
      copy.append(detail, textPart("byline", masked ? "" : item.author));
      front.append(art, copy, part("binding"));
    } else {
      copy.append(iconMark(masked ? { mark: "auto" } : a, a.variant === "full"));
      front.append(art, copy, part("skin"), part("hinge"));
    }
    volume.append(part("volume-back"), part("pages"), front);
    shell.append(volume);
  } else if (item.type === "document") {
    if (a.fastener === "clip") shell.append(clip(true));
    shell.append(part("leaf layer-three"), part("leaf layer-two"));
    front.append(iconMark(masked ? { mark: "triangle" } : a, false), title, detail, part("rules"));
    shell.append(front, a.fastener === "clip" ? clip(false) : part("fastener"));
  } else if (item.type === "note") {
    front.append(title, detail);
    shell.append(front, part("attachment"));
  } else {
    const photo = part("portrait");
    if (pic) photo.append(pic);
    else photo.append(part("avatar"));
    front.append(photo, title, detail, part("rules"));
    shell.append(front);
  }
  return shell;
}
