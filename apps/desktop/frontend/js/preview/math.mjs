/** Typeset engine-generated math wrappers with the publisher's offline MathJax.
 * Never scan prose or code for delimiters, and never execute document HTML.
 */
let startup;
let queue = Promise.resolve();
const cache = new Map();
const MAX_CACHE = 256;

export function mathSource(value, display = false) {
  const text = String(value || "").trim();
  const delimiters = display
    ? [/^\$\$([\s\S]*)\$\$$/, /^\\+\[([\s\S]*?)\\+\]$/]
    : [/^\\+\(([\s\S]*?)\\+\)$/, /^\$([^$][\s\S]*?)\$$/];
  for (const pattern of delimiters) {
    const match = pattern.exec(text);
    if (match) return match[1].trim();
  }
  return text;
}

function loadMathJax() {
  if (startup) return startup;
  startup = new Promise((resolve, reject) => {
    globalThis.MathJax = {
      startup: { typeset: false },
      // Every package is already inside tex-svg-full. In particular, omit
      // require/autoload and HTML commands: a document cannot load scripts or
      // turn TeX into active links or arbitrary styled application elements.
      tex: {
        packages: ["base", "ams", "newcommand", "noerrors", "noundefined", "boldsymbol", "braket", "cancel", "color", "mathtools", "textmacros", "verb"],
        maxMacros: 1000,
        maxBuffer: 16 * 1024,
      },
      // Paths stay inside each SVG, without shared IDs. Reading and Split can
      // coexist, and the page deck can clone sheets without broken glyphs.
      svg: { fontCache: "none" },
      options: { enableMenu: false },
    };
    const script = document.createElement("script");
    script.src = new URL("../vendor/mathjax/tex-svg-full.js", import.meta.url).href;
    script.addEventListener("load", () => {
      Promise.resolve(globalThis.MathJax?.startup?.promise).then(() => {
        if (typeof globalThis.MathJax?.tex2svgPromise !== "function") reject(new Error("MathJax unavailable"));
        else resolve(globalThis.MathJax);
      }, reject);
    }, { once: true });
    script.addEventListener("error", () => reject(new Error("Offline MathJax could not be loaded")), { once: true });
    document.head.append(script);
  }).catch((error) => {
    startup = undefined;
    throw error;
  });
  return startup;
}

/** Remove active attributes even if a future bundled TeX package emits them. */
function inertMath(node) {
  node.querySelectorAll("script,style,foreignObject,iframe,object,embed,a").forEach((element) => {
    if (element.localName === "a") element.replaceWith(...element.childNodes);
    else element.remove();
  });
  for (const element of [node, ...node.querySelectorAll("*")]) {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || name === "id" || name === "href" || name === "xlink:href"
        || (name === "style" && /url\s*\(|position\s*:/i.test(attribute.value))) {
        element.removeAttribute(attribute.name);
      }
    }
  }
  // MathJax's assistive MathML normally relies on a stylesheet injected into
  // its own document. Our SVG is also cloned into an isolated paper frame,
  // so carry the fixed accessibility presentation with the generated node.
  // Otherwise the browser paints MathML beside the SVG as a second formula.
  for (const assistive of node.querySelectorAll("mjx-assistive-mml")) {
    assistive.style.cssText = "position:absolute!important;clip:rect(1px,1px,1px,1px)!important;clip-path:inset(50%)!important;width:1px!important;height:1px!important;overflow:hidden!important;padding:0!important;border:0!important;white-space:nowrap!important";
  }
  if (node.querySelector("mjx-assistive-mml")) node.style.position = "relative";
  return node;
}

export function typesetPreviewMath(container, {
  isCurrent = () => true,
  errorLabel = "This formula could not be rendered. Its TeX source is shown.",
} = {}) {
  const expressions = [...container.querySelectorAll(".math")]
    .filter((element) => !element.closest("pre,code") && !element.querySelector("mjx-container"));
  if (!expressions.length) return Promise.resolve({ rendered: 0, failed: 0 });
  const job = async () => {
    if (!isCurrent()) return { rendered: 0, failed: 0 };
    let mathjax;
    try { mathjax = await loadMathJax(); }
    catch {
      if (isCurrent()) for (const element of expressions) {
        element.dataset.mathError = "true";
        element.title = errorLabel;
      }
      return { rendered: 0, failed: expressions.length };
    }
    let rendered = 0;
    let failed = 0;
    for (const element of expressions) {
      if (!isCurrent() || !container.contains(element)) break;
      const display = element.classList.contains("display");
      const source = mathSource(element.textContent, display);
      const fontSize = Number.parseFloat(container.ownerDocument.defaultView.getComputedStyle(element).fontSize) || 18;
      const key = `${display}:${fontSize}:${source}`;
      try {
        let node = cache.get(key)?.cloneNode(true);
        if (!node) {
          mathjax.texReset();
          node = inertMath(await mathjax.tex2svgPromise(source, {
            display, em: fontSize, ex: fontSize / 2,
            containerWidth: container.clientWidth || 760,
          }));
          cache.set(key, node.cloneNode(true));
          if (cache.size > MAX_CACHE) cache.delete(cache.keys().next().value);
        }
        if (!isCurrent() || !container.contains(element)) break;
        element.dir = "ltr";
        element.setAttribute("aria-label", source);
        element.replaceChildren(container.ownerDocument.importNode(node, true));
        element.dataset.mathRendered = "true";
        if (node.querySelector("[data-mjx-error]")) {
          element.dataset.mathError = "true";
          element.title = errorLabel;
        }
        rendered += 1;
      } catch {
        element.dataset.mathError = "true";
        element.title = errorLabel;
        failed += 1;
      }
    }
    return { rendered, failed };
  };
  const result = queue.then(job, job);
  queue = result.catch(() => {});
  return result;
}
