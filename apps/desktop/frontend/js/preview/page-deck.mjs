/**
 * The export preview: real sheets of paper, drawn from the engine's own page.
 *
 * The engine hands over the exact composition the exporter prints — cover,
 * contents, body, bibliography, watermark, every stylesheet, the running
 * footer, and the page geometry. This module lays that out as paper: a sheet
 * of the configured size, the configured margins drawn as real margins, and
 * the document flowed across as many pages as it takes.
 *
 * Three decisions carry the fidelity:
 *
 *   - The page is drawn inside a same-origin frame rather than a shadow root.
 *     The engine's stylesheets are written for a whole printed document: the
 *     palette and the type scale are declared on `:root`, and the appearance,
 *     direction and page-break rules are all `body.md2pdf-…` selectors.
 *     Neither selector can match inside a shadow tree, so a shadow-root
 *     preview silently loses the palette, the dark mode, the fonts and the
 *     break rules — which is most of what the preview exists to show.
 *   - The content is measured once, at 1:1 CSS pixels, and each sheet shows a
 *     window onto that single measured flow. Zoom is a transform applied
 *     afterwards, so changing it cannot change where a page ends.
 *   - Where a page ends comes from the computed break rules of the document's
 *     own blocks, so the engine's "contents on its own page" and "every H1
 *     starts a page" appear here without this module knowing they exist.
 */

import {
  currentPageNumber,
  fitPageZoom,
  fitWidthZoom,
  lineSnapper,
  normalizePageGeometry,
  paginate,
  stepZoom,
  visiblePageRange,
} from "../core/page-preview.mjs";

/** Elements that have no business in a preview of a printed page. */
const FORBIDDEN_TAGS =
  "script,iframe,object,embed,link,meta,base,form,input,button,select,textarea,noscript";

/** Sheets kept in the DOM around the viewport; the rest stay blank paper. */
const OVERSCAN_PAGES = 1;

/** Space between sheets, and around the deck, in unscaled pixels. */
const SHEET_GAP = 20;

/**
 * Strip anything active out of engine HTML.
 *
 * The markup is produced by the engine from the user's own document, so the
 * risk is a crafted document rather than a hostile server — but a preview
 * renders untrusted prose, and the cheapest safe posture is to allow no
 * behaviour at all. Inline `style` survives because table alignment and
 * diagram colours live there, and element ids survive because rewriting them
 * breaks the `url(#id)` references Mermaid arrowheads depend on.
 */
function sanitizePageHtml(ownerDocument, value) {
  const template = ownerDocument.createElement("template");
  template.innerHTML = String(value || "");
  for (const element of template.content.querySelectorAll(FORBIDDEN_TAGS)) element.remove();
  for (const element of template.content.querySelectorAll("*")) {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || ["srcdoc", "srcset", "ping", "formaction"].includes(name)) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (name === "style" && /url\(\s*(?!['"]?data:)/i.test(attribute.value)) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (name === "href" && !attribute.value.startsWith("#")) {
        element.removeAttribute(attribute.name);
        element.setAttribute("aria-disabled", "true");
        continue;
      }
      if (name === "src" && !/^\s*data:/i.test(attribute.value)) {
        element.removeAttribute(attribute.name);
      }
    }
  }
  return template.content;
}

/**
 * Line boxes cap: past this the document is long enough that measuring every
 * line costs more than the extra fidelity is worth, and pages fall back to
 * splitting at the margin.
 */
const MAX_MEASURED_LINES = 20_000;

/**
 * Every line box in the flow, as offsets from its top.
 *
 * A printer never cuts through a line of text, so neither should the preview.
 * Where a line of mixed Persian and English actually breaks is something only
 * the layout engine knows, so it is asked directly.
 */
function collectLineTops(root, flowTop) {
  const ownerDocument = root.ownerDocument;
  const walker = ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const range = ownerDocument.createRange();
  const tops = [];
  let node = walker.nextNode();
  while (node) {
    if (node.data && node.data.trim()) {
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (rect.height <= 0) continue;
        tops.push(rect.top - flowTop);
        if (tops.length >= MAX_MEASURED_LINES) return tops;
      }
    }
    node = walker.nextNode();
  }
  return tops;
}

/** Read one block's break rules out of its computed style. */
function blockMetrics(view, element, flowTop) {
  const style = view.getComputedStyle(element);
  const before = `${style.breakBefore || ""} ${style.pageBreakBefore || ""}`;
  const after = `${style.breakAfter || ""} ${style.pageBreakAfter || ""}`;
  const inside = `${style.breakInside || ""} ${style.pageBreakInside || ""}`;
  const box = element.getBoundingClientRect();
  return {
    top: box.top - flowTop,
    height: box.height,
    breakBefore: /\b(page|always|left|right)\b/.test(before),
    breakAfter: /\b(page|always|left|right)\b/.test(after),
    breakInside: /\bavoid\b/.test(inside),
    keepWithNext: /\bavoid\b/.test(after),
  };
}

/**
 * Styling for the paper itself.
 *
 * Loaded after the engine's stylesheets so it can undo the few rules that
 * assume a real printed page: the white document background, and the
 * full-bleed cover's `100vh`, which inside a frame would be the frame rather
 * than the sheet.
 */
const DECK_CSS = `
html.pv-frame {
  height: 100%;
  background: #6f6f6f !important;
  overflow: auto;
  scrollbar-width: thin;
}
html.pv-frame.pv-dark { background: #2a2a2a !important; }
body.pv-frame-body {
  margin: 0 !important;
  min-height: 100%;
  background: transparent !important;
  padding: ${SHEET_GAP}px 0;
}
/* The scaffolding is deliberately physical, never logical: a right-to-left
   document flips the inline-start edge, which would push the scaled deck out
   of its own canvas. Direction belongs to the text on the page, not to the
   paper the page is printed on. */
.pv-canvas { position: relative; margin: 0 auto; direction: ltr; }
.pv-stage { position: absolute; top: 0; left: 0; transform-origin: top left; }
.pv-page {
  position: absolute;
  left: 0;
  width: var(--pv-sheet-w);
  height: var(--pv-sheet-h);
  background: #ffffff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.35);
  overflow: hidden;
}
body.md2pdf-mode-dark .pv-page { background: #0f172a; }
.pv-window {
  position: absolute;
  overflow: hidden;
  top: var(--pv-margin-top);
  bottom: var(--pv-margin-bottom);
  left: var(--pv-margin-x);
  right: var(--pv-margin-x);
}
/* The exporter prints the cover full bleed as its own PDF: no margin box, no
   running footer, no page furniture. */
.pv-page[data-kind="cover"] .pv-window { inset: 0; }
.pv-flow { position: absolute; left: 0; right: 0; top: 0; }
.pv-flow > .md2pdf-document { margin: 0; }
.pv-footer {
  position: absolute;
  left: var(--pv-margin-x);
  right: var(--pv-margin-x);
  bottom: 0;
  height: var(--pv-margin-bottom);
  display: flex;
  align-items: center;
  overflow: hidden;
}
.pv-footer > * { width: 100%; }
.pv-watermark { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.pv-guide {
  position: absolute;
  top: var(--pv-margin-top);
  bottom: var(--pv-margin-bottom);
  left: var(--pv-margin-x);
  right: var(--pv-margin-x);
  border: 1px dashed rgba(140, 140, 140, 0.55);
  pointer-events: none;
  display: none;
}
body[data-guides="true"] .pv-page:not([data-kind="cover"]) .pv-guide { display: block; }
.pv-number {
  position: absolute;
  right: 8px;
  top: 8px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(20, 20, 20, 0.55);
  color: #ffffff;
  font: 600 9.5px/1.7 system-ui, sans-serif;
  direction: ltr;
  opacity: 0;
  transition: opacity 120ms ease;
}
.pv-page:hover .pv-number { opacity: 1; }
.pv-measure {
  position: fixed;
  top: 0;
  left: 0;
  z-index: -1;
  visibility: hidden;
  pointer-events: none;
  width: var(--pv-content-w);
}
.pv-note {
  margin: 0;
  padding: 40px 20px 0;
  color: #f0f0f0;
  font: 12.5px/1.75 system-ui, sans-serif;
  text-align: center;
}
.pv-note-details {
  margin: 16px auto 40px;
  padding: 0;
  max-width: 52ch;
  list-style: none;
  color: #c8c8c8;
  font: 12px/1.6 system-ui, sans-serif;
}
.pv-note-details li {
  margin-top: 8px;
  padding: 8px 12px;
  border-inline-start: 2px solid #f97316;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
  text-align: start;
  overflow-wrap: anywhere;
}
.md2pdf-cover-full-bleed .md2pdf-document,
.md2pdf-cover-full-bleed .md2pdf-article,
.md2pdf-cover-full-bleed .md2pdf-cover { min-height: var(--pv-sheet-h) !important; }
.md2pdf-watermark { position: absolute !important; inset: 0 !important; }
/* Heading anchors are an authoring affordance; printed paper has none. */
.heading-anchor, a.heading-anchor { display: none !important; }
img, svg { max-width: 100%; }
`;

const BLANK_DOCUMENT =
  '<!doctype html><html class="pv-frame"><head><meta charset="utf-8">'
  + '<style id="pv-engine"></style><style id="pv-deck"></style></head>'
  + '<body class="pv-frame-body"></body></html>';

/**
 * Mount a page deck inside `host`.
 *
 * The frame is created once and reused; each render replaces its stylesheets
 * and sheets rather than the frame, so scroll position and zoom survive
 * changing a single option — which is the whole point of a live preview.
 */
export function createPageDeck(host, { onState } = {}) {
  const frame = document.createElement("iframe");
  frame.className = "pv-frame-element";
  frame.setAttribute("title", host.getAttribute("aria-label") || "PDF preview");
  // Sized here rather than in the application stylesheet: the frame's own box
  // is what "fit width" measures, so the deck cannot afford to inherit a
  // default 300×150 replaced-element size if a rule is ever missed.
  frame.style.cssText = "display:block;width:100%;height:100%;border:0;background:transparent";
  // An `about:blank` frame written into from here, rather than `srcdoc`: it is
  // same-origin without argument, and no content-security policy has to be
  // widened to permit it.
  host.replaceChildren(frame);

  const state = {
    ready: false,
    geometry: normalizePageGeometry({}),
    pages: [],
    zoom: 1,
    zoomMode: "fit-width",
    guides: false,
    source: null,
    coverSource: null,
    footerSource: null,
    watermarkSource: null,
    sheets: [],
    pitch: 0,
    frameRequest: 0,
    pending: null,
    // Kept so the deck can be restored if the frame's document is replaced.
    lastPayload: null,
    lastMessage: null,
    lastDetails: [],
  };

  const view = () => frame.contentWindow;
  const doc = () => frame.contentDocument;
  const scroller = () => doc()?.scrollingElement || doc()?.documentElement || null;

  function publish() {
    const box = scroller();
    onState?.({
      pageCount: state.sheets.length,
      currentPage: box
        ? currentPageNumber(box.scrollTop, box.clientHeight, state.pitch * state.zoom, state.sheets.length)
        : 1,
      zoom: state.zoom,
      zoomMode: state.zoomMode,
      guides: state.guides,
    });
  }

  /** Attach or drop page contents so a long document stays light. */
  function materialise() {
    const box = scroller();
    if (!box || !state.sheets.length) return;
    const { first, last } = visiblePageRange(
      box.scrollTop,
      box.clientHeight,
      state.pitch * state.zoom,
      state.sheets.length,
      OVERSCAN_PAGES,
    );
    for (let index = 0; index < state.sheets.length; index += 1) {
      const sheet = state.sheets[index];
      const wanted = index >= first && index <= last;
      if (wanted === sheet.filled) continue;
      sheet.filled = wanted;
      if (!wanted) {
        sheet.flow.replaceChildren();
        continue;
      }
      const source = sheet.kind === "cover" ? state.coverSource : state.source;
      if (!source) continue;
      sheet.flow.append(source.cloneNode(true));
      sheet.flow.style.transform = `translateY(${-sheet.offset}px)`;
    }
    publish();
  }

  function onScroll() {
    if (state.frameRequest) return;
    const raf = view()?.requestAnimationFrame || globalThis.requestAnimationFrame;
    state.frameRequest = raf.call(view() || globalThis, () => {
      state.frameRequest = 0;
      materialise();
    });
  }

  function applyZoom() {
    const document_ = doc();
    if (!document_) return;
    const canvas = document_.querySelector(".pv-canvas");
    const stage = document_.querySelector(".pv-stage");
    if (!canvas || !stage) return;
    const height = state.pitch * state.sheets.length;
    stage.style.width = `${state.geometry.widthPx}px`;
    stage.style.height = `${height}px`;
    stage.style.transform = `scale(${state.zoom})`;
    // The transform does not change layout, so the scrollable box has to be
    // told the scaled size or long documents cannot be scrolled to the end.
    canvas.style.width = `${state.geometry.widthPx * state.zoom}px`;
    canvas.style.height = `${Math.max(0, height - SHEET_GAP) * state.zoom}px`;
    publish();
  }

  function recomputeFit() {
    const box = scroller();
    if (!box) return;
    if (state.zoomMode === "fit-width") {
      state.zoom = fitWidthZoom(box.clientWidth, state.geometry.widthPx, SHEET_GAP * 2);
    } else if (state.zoomMode === "fit-page") {
      state.zoom = fitPageZoom(
        box.clientWidth,
        box.clientHeight,
        state.geometry,
        SHEET_GAP * 2,
      );
    }
    applyZoom();
  }

  const resize = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
        recomputeFit();
        materialise();
      })
    : null;
  resize?.observe(host);

  function buildSheets(stage) {
    const document_ = doc();
    stage.replaceChildren();
    state.sheets = [];
    state.pitch = state.geometry.heightPx + SHEET_GAP;

    const makeSheet = (kind, offset, number) => {
      const page = document_.createElement("div");
      page.className = "pv-page";
      page.dataset.kind = kind;
      page.style.top = `${state.sheets.length * state.pitch}px`;

      if (kind !== "cover" && state.watermarkSource) {
        const watermark = document_.createElement("div");
        watermark.className = "pv-watermark";
        watermark.append(state.watermarkSource.cloneNode(true));
        page.append(watermark);
      }

      const window_ = document_.createElement("div");
      window_.className = "pv-window";
      const flow = document_.createElement("div");
      flow.className = "pv-flow";
      window_.append(flow);
      page.append(window_);

      if (kind !== "cover") {
        const guide = document_.createElement("div");
        guide.className = "pv-guide";
        page.append(guide);
        if (state.footerSource) {
          const footer = document_.createElement("div");
          footer.className = "pv-footer";
          footer.append(state.footerSource.cloneNode(true));
          page.append(footer);
        }
      }

      const badge = document_.createElement("span");
      badge.className = "pv-number";
      badge.textContent = String(number);
      page.append(badge);

      stage.append(page);
      state.sheets.push({ kind, offset, flow, page, filled: false });
    };

    let number = 1;
    if (state.coverSource) makeSheet("cover", 0, number++);
    for (const offset of state.pages) makeSheet("content", offset, number++);

    // The running footer numbers printed sheets, and the cover carries none —
    // exactly how the merged PDF is numbered.
    const total = state.sheets.length;
    let printed = 0;
    for (const sheet of state.sheets) {
      printed += 1;
      if (sheet.kind === "cover") continue;
      for (const node of sheet.page.querySelectorAll(".pv-footer .pageNumber")) {
        node.textContent = String(printed);
      }
      for (const node of sheet.page.querySelectorAll(".pv-footer .totalPages")) {
        node.textContent = String(total);
      }
    }
  }

  function draw(payload) {
    const document_ = doc();
    const window_ = view();
    if (!document_ || !window_) return;
    state.lastPayload = payload;
    state.lastMessage = null;
    state.lastDetails = [];

    state.geometry = normalizePageGeometry(payload?.page);
    const geometry = state.geometry;

    document_.getElementById("pv-engine").textContent = [
      payload?.css?.fonts || "",
      payload?.css?.pygments || "",
      payload?.css?.style || "",
      payload?.css?.palette || "",
      payload?.css?.layout || "",
    ].join("\n");
    document_.getElementById("pv-deck").textContent = DECK_CSS;

    const root = document_.documentElement;
    root.className = "pv-frame";
    root.lang = String(payload?.lang || "en");
    root.dir = payload?.direction === "rtl" ? "rtl" : "ltr";
    if (String(payload?.body_classes || "").includes("md2pdf-mode-dark")) {
      root.classList.add("pv-dark");
    }

    const body = document_.body;
    // The cover's only extra class is the full-bleed marker; carrying it on the
    // shared body lets the cover sheet style itself, and the deck stylesheet
    // stops it reaching the content pages.
    const coverClasses = String(payload?.cover?.body_classes || "")
      .split(/\s+/)
      .filter((name) => name === "md2pdf-cover-full-bleed");
    body.className = ["pv-frame-body", payload?.body_classes || "", ...coverClasses]
      .join(" ")
      .trim();
    body.dataset.guides = String(state.guides);
    body.style.setProperty("--pv-sheet-w", `${geometry.widthPx}px`);
    body.style.setProperty("--pv-sheet-h", `${geometry.heightPx}px`);
    body.style.setProperty("--pv-margin-top", `${geometry.marginTopPx}px`);
    body.style.setProperty("--pv-margin-bottom", `${geometry.marginBottomPx}px`);
    body.style.setProperty("--pv-margin-x", `${geometry.marginXPx}px`);
    body.style.setProperty("--pv-content-w", `${geometry.contentWidthPx}px`);

    const canvas = document_.createElement("div");
    canvas.className = "pv-canvas";
    const stage = document_.createElement("div");
    stage.className = "pv-stage";
    canvas.append(stage);

    const measure = document_.createElement("div");
    measure.className = "pv-measure";
    const flowRoot = document_.createElement("main");
    flowRoot.className = "md2pdf-document";
    const article = document_.createElement("article");
    article.className = "md2pdf-article";
    article.append(sanitizePageHtml(document_, payload?.content_html));
    flowRoot.append(article);
    measure.append(flowRoot);
    body.replaceChildren(canvas, measure);

    const flowTop = article.getBoundingClientRect().top;
    const blocks = [];
    for (const child of article.children) {
      if (typeof child.getBoundingClientRect !== "function") continue;
      blocks.push(blockMetrics(window_, child, flowTop));
    }
    const total = article.getBoundingClientRect().height;
    state.pages = paginate(blocks, geometry.contentHeightPx, total, {
      snap: lineSnapper(collectLineTops(article, flowTop)),
    });
    state.source = flowRoot.cloneNode(true);

    if (payload?.cover?.html) {
      const coverRoot = document_.createElement("main");
      coverRoot.className = "md2pdf-document";
      const coverArticle = document_.createElement("article");
      coverArticle.className = "md2pdf-article";
      coverArticle.append(sanitizePageHtml(document_, payload.cover.html));
      coverRoot.append(coverArticle);
      state.coverSource = coverRoot;
    } else {
      state.coverSource = null;
    }

    const wrap = (html) => {
      const holder = document_.createElement("div");
      holder.append(sanitizePageHtml(document_, html));
      return holder;
    };
    state.watermarkSource = payload?.watermark_html ? wrap(payload.watermark_html) : null;
    state.footerSource = payload?.footer?.enabled && payload.footer.html
      ? wrap(payload.footer.html)
      : null;

    // The measuring copy has done its job; keeping it doubles the DOM.
    measure.remove();

    buildSheets(stage);
    recomputeFit();
    materialise();
  }

  function showMessageNow(text, details) {
    const document_ = doc();
    if (!document_) return;
    const lines = (Array.isArray(details) ? details : []).map(String).filter(Boolean);
    state.lastMessage = String(text || "");
    state.lastDetails = lines;
    state.lastPayload = null;
    document_.getElementById("pv-engine").textContent = "";
    document_.getElementById("pv-deck").textContent = DECK_CSS;
    document_.documentElement.className = "pv-frame";
    document_.body.className = "pv-frame-body";
    state.sheets = [];
    state.pages = [];
    state.source = null;
    const note = document_.createElement("p");
    note.className = "pv-note";
    note.textContent = String(text || "");
    const nodes = [note];
    if (lines.length) {
      const list = document_.createElement("ul");
      list.className = "pv-note-details";
      // `dir="auto"` because a diagnostic quotes the document, and a Persian
      // document's citation keys and headings arrive mixed with Latin codes.
      list.dir = "auto";
      for (const line of lines) {
        const item = document_.createElement("li");
        item.textContent = line;
        list.append(item);
      }
      nodes.push(list);
    }
    document_.body.replaceChildren(...nodes);
    publish();
  }

  function attach() {
    const window_ = view();
    const document_ = doc();
    if (!window_ || !document_ || state.ready) return;
    document_.open();
    document_.write(BLANK_DOCUMENT);
    document_.close();
    state.ready = true;
    window_.addEventListener("scroll", onScroll, { passive: true });
    const pending = state.pending;
    state.pending = null;
    if (pending?.kind === "payload") draw(pending.value);
    else if (pending?.kind === "message") showMessageNow(pending.value, pending.details);
  }

  /**
   * Re-establish the frame if the engine replaces its document under us.
   *
   * Writing into the initial `about:blank` is the standard way to own a frame's
   * document, but the three webviews this app ships on — WebView2, WKWebView
   * and WebKitGTK — do not all sequence that initial load identically, and a
   * late navigation would silently discard the deck. Rather than assume, the
   * last payload is kept and redrawn whenever the frame reports a load it did
   * not get from us.
   */
  function reattach() {
    if (!state.ready) {
      attach();
      return;
    }
    const document_ = doc();
    if (!document_ || document_.getElementById("pv-deck")) return;
    state.ready = false;
    attach();
    if (state.lastPayload) draw(state.lastPayload);
    else if (state.lastMessage !== null) showMessageNow(state.lastMessage, state.lastDetails);
  }

  // A frame with no source is already an about:blank document by the time it is
  // in the tree; the load listener only covers engines that disagree.
  attach();
  frame.addEventListener("load", reattach);

  return {
    /** Draw a `preview.document_page` payload. */
    render(payload) {
      if (!state.ready) {
        state.pending = { kind: "payload", value: payload };
        return;
      }
      draw(payload);
    },

    /**
     * Show a short message instead of a document.
     *
     * `details` carries the engine's own diagnostics — the lines that say which
     * citation key or heading is at fault. Without them the panel can only
     * report that something failed, which is not something a user can act on.
     */
    showMessage(text, details) {
      if (!state.ready) {
        state.pending = { kind: "message", value: text, details };
        return;
      }
      showMessageNow(text, details);
    },

    zoomBy(direction) {
      state.zoomMode = "manual";
      state.zoom = stepZoom(state.zoom, direction);
      applyZoom();
      materialise();
    },

    setZoomMode(mode) {
      state.zoomMode = mode === "fit-page" ? "fit-page" : "fit-width";
      recomputeFit();
      materialise();
    },

    toggleGuides(force) {
      state.guides = force === undefined ? !state.guides : Boolean(force);
      const body = doc()?.body;
      if (body) body.dataset.guides = String(state.guides);
      publish();
    },

    goToPage(number) {
      const box = scroller();
      if (!box || !state.sheets.length) return;
      const index = Math.min(
        Math.max(1, Math.trunc(Number(number) || 1)),
        state.sheets.length,
      ) - 1;
      box.scrollTop = index * state.pitch * state.zoom;
      materialise();
    },

    get pageCount() {
      return state.sheets.length;
    },

    destroy() {
      view()?.removeEventListener("scroll", onScroll);
      resize?.disconnect();
      frame.remove();
    },
  };
}
