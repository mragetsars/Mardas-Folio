/**
 * Online image display is an explicit, per-document action. This module owns
 * no grants: the caller supplies an existing grant or records the requested
 * origin in its own document/session state.
 *
 * This is a URL boundary, not a DNS resolver or redirect firewall. An HTTPS
 * hostname's eventual address and redirects remain browser/network concerns.
 */

const LOCAL_SUFFIXES = [
  "localhost", "local", "localdomain", "internal", "intranet", "lan", "home",
  "home.arpa", "test", "invalid", "onion",
];

/** A normalized public-looking HTTPS destination, or null. Never a local URL. */
export function safeOnlineImageURL(source) {
  if (typeof source !== "string") return null;
  const candidate = source.trim();
  if (!candidate || candidate.length > 8192 || /[\u0000-\u001f\u007f\\]/.test(candidate)
      || candidate.startsWith("///")) return null;
  let url;
  try { url = new URL(candidate.startsWith("//") ? `https:${candidate}` : candidate); }
  catch { return null; }
  if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
  // URL normalizes octal, hexadecimal and abbreviated IPv4 forms before this
  // check. Requiring a real domain suffix also rejects all numeric addresses.
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  const labels = host.split(".");
  if (host.length > 253 || labels.length < 2
      || !labels.every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))
      || !/^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$/.test(labels.at(-1))
      || LOCAL_SUFFIXES.some(suffix => host === suffix || host.endsWith(`.${suffix}`))) return null;
  url.hostname = host;
  return url.href;
}

/**
 * Create a safe display/control without modifying Markdown. `onRequest` is
 * called only from the Load button, with (origin, normalizedURL); it must
 * return true to grant this request. A rejected/failed request stays local.
 * A failed image has a Retry button, never a broken-image glyph.
 */
export function onlineImageControl(document, {
  source, alt = "", allowed = false, onRequest, strings = {},
} = {}) {
  const url = safeOnlineImageURL(source);
  const origin = url ? new URL(url).origin : "";
  const label = (key, fallback) => typeof strings[key] === "string" && strings[key]
    ? strings[key] : fallback;
  const text = typeof alt === "string" ? alt : "";
  const root = document.createElement("span");
  root.className = "online-image-control";
  root.contentEditable = "false";
  root.dataset.onlineImageOrigin = origin;
  root.setAttribute("dir", "auto");
  let granted = allowed === true;
  let pending = false;
  let request = 0;

  function message(state) {
    const heading = document.createElement("span");
    heading.className = "online-image-label";
    heading.textContent = state === "loading"
      ? label("remoteImageLoading", "Loading online image…")
      : state === "error" ? label("remoteImageFailed", "Image could not be loaded")
        : state === "invalid" ? label("remoteImageBlocked", "Unsupported online image address")
          : label("remoteImageNotLoaded", "Online image not loaded");
    const status = document.createElement("span");
    status.className = "online-image-status";
    status.setAttribute("role", "status");
    status.append(heading);
    const children = [status];
    if (origin) {
      const host = document.createElement("code");
      host.className = "online-image-origin";
      host.dir = "ltr";
      host.textContent = origin;
      host.title = url;
      children.push(host);
    }
    if (text) {
      const caption = document.createElement("span");
      caption.className = "online-image-alt";
      caption.textContent = text;
      children.push(caption);
    }
    if (url && state !== "loading") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "online-image-load";
      button.textContent = state === "error"
        ? label("retryRemoteImage", "Retry") : label("loadRemoteImages", "Load images");
      button.setAttribute("aria-label", `${button.textContent} — ${origin}`);
      button.title = `${button.textContent} — ${origin}`;
      button.addEventListener("mousedown", event => event.stopPropagation());
      button.addEventListener("click", async event => {
        event.preventDefault();
        event.stopPropagation();
        if (pending) return;
        pending = true;
        // aria-disabled + the pending guard coalesce activation while keeping
        // focus on the button until the replacement status can inherit it.
        button.setAttribute("aria-disabled", "true");
        try {
          if (!granted) granted = typeof onRequest === "function"
            && await onRequest(origin, url) === true;
          if (granted) load();
          else show("blocked");
        } catch { show("error"); }
        finally { pending = false; }
      });
      children.push(button);
    }
    return children;
  }

  function show(state) {
    const hadFocus = typeof root.contains === "function" && root.contains(document.activeElement);
    root.dataset.onlineImageState = state;
    root.replaceChildren(...message(state));
    // Loading/error updates replace the button. Keep keyboard focus at the
    // image's document position instead of dropping it to the page's start.
    if (hadFocus && typeof root.focus === "function") {
      root.tabIndex = -1;
      root.focus({ preventScroll: true });
    }
  }

  function load() {
    if (!url || !granted) return;
    const current = ++request;
    show("loading");
    const target = document.createElement("img");
    target.alt = text;
    target.loading = "lazy";
    target.decoding = "async";
    target.referrerPolicy = "no-referrer";
    target.className = "online-image";
    target.addEventListener("load", () => {
      if (current !== request) return;
      target.style.visibility = "";
      root.dataset.onlineImageState = "loaded";
      root.replaceChildren(target);
    });
    target.addEventListener("error", () => {
      if (current !== request) return;
      show("error");
    });
    // The request-capable element is created only after a grant. Keeping it
    // hidden until load avoids both the broken-image glyph and stale alt text.
    target.style.visibility = "hidden";
    root.append(target);
    target.src = url;
  }

  if (!url) show("invalid");
  else if (granted) load();
  else show("blocked");
  return root;
}
