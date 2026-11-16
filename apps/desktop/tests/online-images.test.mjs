import test from "node:test";
import assert from "node:assert/strict";

import { onlineImageControl, safeOnlineImageURL } from "../frontend/js/preview/online-images.mjs";

test("online image URLs normalize HTTPS and protocol-relative public domains", () => {
  assert.equal(safeOnlineImageURL("//img.shields.io/badge/Renderer-Playwright%20%2B%20Chromium-green.svg"),
    "https://img.shields.io/badge/Renderer-Playwright%20%2B%20Chromium-green.svg");
  assert.equal(safeOnlineImageURL(" https://IMAGES.EXAMPLE.COM.:443/a b.png?q=1#fragment "),
    "https://images.example.com/a%20b.png?q=1#fragment");
  assert.equal(safeOnlineImageURL("https://مثال.com/chart.png"), new URL("https://مثال.com/chart.png").href);
});

test("unsafe, local, numeric and credential-bearing destinations never become online images", () => {
  for (const value of [null, {}, "", "image.png", "../image.png", "http://example.com/i.png",
    "file:///C:/private.png", "data:image/svg+xml,<svg/>", "javascript:alert(1)",
    "blob:https://example.com/id", "https://user@example.com/a.png", "https://user:pass@example.com/a.png",
    "https://example.com:8443/a.png", "https://localhost/a.png", "https://localhost./a.png",
    "https://foo.local/a.png", "https://foo.localhost/a.png", "https://server.internal/a.png",
    "https://printer.lan/a.png", "https://router.home.arpa/a.png", "https://example.test/a.png",
    "https://example.invalid/a.png", "https://service.onion/a.png", "https://intranet/a.png",
    "https://127.0.0.1/a.png", "https://10.0.0.1/a.png", "https://192.168.1.1/a.png",
    "https://2130706433/a.png", "https://0177.0.0.1/a.png", "https://0x7f000001/a.png",
    "https://127.1/a.png", "https://[::1]/a.png", "https://[2001:db8::1]/a.png",
    "https://user\\@example.com/a.png", "https://example.com/\na.png", "///example.com/a.png",
    `https://example.com/${"x".repeat(8192)}`]) {
    assert.equal(safeOnlineImageURL(value), null, String(value));
  }
});

function documentFixture() {
  const created = [];
  const document = {
    createElement(tag) {
      const node = {
        tag, children: [], attributes: {}, dataset: {}, style: {}, handlers: {},
        textContent: "", className: "",
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        contains(other) { return this === other || this.children.some(child => child.contains?.(other)); },
        focus(options) { document.activeElement = this; this.lastFocusOptions = options; },
        setAttribute(name, value) { this.attributes[name] = String(value); },
        addEventListener(name, callback) { (this.handlers[name] ||= []).push(callback); },
        async fire(name) {
          const event = { preventDefault() {}, stopPropagation() {} };
          for (const callback of this.handlers[name] || []) await callback(event);
        },
      };
      Object.defineProperty(node, "innerHTML", { set() { throw new Error("Unsafe HTML sink"); } });
      created.push(node);
      return node;
    },
  };
  return { document, created, last: tag => created.filter(node => node.tag === tag).at(-1) };
}

test("a blocked image creates no request-capable element before explicit origin approval", async () => {
  const fixture = documentFixture();
  const requests = [];
  const control = onlineImageControl(fixture.document, {
    source: "//images.example.com/a.png", alt: '<img src=x onerror="alert(1)">',
    strings: { loadRemoteImages: "بارگیری تصاویر" },
    onRequest: (...args) => { requests.push(args); return true; },
  });
  assert.equal(control.dataset.onlineImageState, "blocked");
  assert.equal(fixture.last("img"), undefined);
  assert.deepEqual(requests, []);
  assert.equal(fixture.created.find(node => node.className === "online-image-alt").textContent,
    '<img src=x onerror="alert(1)">');
  const button = fixture.last("button");
  assert.equal(button.type, "button");
  assert.equal(button.textContent, "بارگیری تصاویر");
  assert.match(button.attributes["aria-label"], /https:\/\/images\.example\.com/);
  await button.fire("click");
  assert.deepEqual(requests, [["https://images.example.com", "https://images.example.com/a.png"]]);
  const image = fixture.last("img");
  assert.equal(image.src, "https://images.example.com/a.png");
  assert.equal(image.alt, '<img src=x onerror="alert(1)">');
  assert.equal(image.referrerPolicy, "no-referrer");
  assert.equal(image.loading, "lazy");
  assert.equal(image.decoding, "async");
  assert.equal(control.dataset.onlineImageState, "loading");
  await image.fire("load");
  assert.equal(control.dataset.onlineImageState, "loaded");
  assert.deepEqual(control.children, [image]);
  assert.equal(image.style.visibility, "");
});

test("a declined or missing grant never starts a request", async () => {
  for (const onRequest of [undefined, () => false, () => undefined]) {
    const fixture = documentFixture();
    const control = onlineImageControl(fixture.document, { source: "https://images.example.com/a.png", onRequest });
    await fixture.last("button").fire("click");
    assert.equal(control.dataset.onlineImageState, "blocked");
    assert.equal(fixture.last("img"), undefined);
  }
});

test("network failure removes the image and offers an accessible retry with the existing grant", async () => {
  const fixture = documentFixture();
  let approvals = 0;
  const control = onlineImageControl(fixture.document, {
    source: "https://images.example.com/a.png", onRequest: () => { approvals++; return true; },
    strings: { remoteImageFailed: "تصویر بارگیری نشد", retryRemoteImage: "تلاش دوباره" },
  });
  await fixture.last("button").fire("click");
  const broken = fixture.last("img");
  await broken.fire("error");
  assert.equal(control.dataset.onlineImageState, "error");
  assert.equal(control.children.includes(broken), false);
  assert.equal(fixture.last("button").textContent, "تلاش دوباره");
  assert.equal(control.children[0].attributes.role, "status");
  assert.equal(control.children[0].children[0].textContent, "تصویر بارگیری نشد");
  await fixture.last("button").fire("click");
  assert.equal(approvals, 1);
  assert.notEqual(fixture.last("img"), broken);
  await broken.fire("load");
  assert.equal(control.dataset.onlineImageState, "loading", "stale image callbacks cannot replace the retry");
  await fixture.last("img").fire("load");
  assert.equal(control.dataset.onlineImageState, "loaded");
});

test("an existing document grant loads directly; invalid addresses override even a supplied grant", () => {
  const fixture = documentFixture();
  onlineImageControl(fixture.document, { source: "https://images.example.com/a.png", allowed: true });
  assert.equal(fixture.last("img").src, "https://images.example.com/a.png");
  const blocked = documentFixture();
  const control = onlineImageControl(blocked.document, { source: "https://127.0.0.1/private.png", allowed: true });
  assert.equal(control.dataset.onlineImageState, "invalid");
  assert.equal(blocked.last("img"), undefined);
  assert.equal(blocked.last("button"), undefined);
});

test("loading and failure keep keyboard focus at the image instead of losing it with the button", async () => {
  const fixture = documentFixture();
  const control = onlineImageControl(fixture.document, {
    source: "https://images.example.com/a.png", onRequest: () => true,
  });
  const button = fixture.last("button");
  button.focus();
  await button.fire("click");
  assert.equal(fixture.document.activeElement, control);
  assert.deepEqual(control.lastFocusOptions, { preventScroll: true });
  await fixture.last("img").fire("error");
  assert.equal(fixture.document.activeElement, control);
  assert.equal(control.tabIndex, -1);
  assert.ok(fixture.last("button"));
});

test("pending approval coalesces repeated clicks and a failed callback remains retryable", async () => {
  const fixture = documentFixture();
  let resolve, calls = 0;
  onlineImageControl(fixture.document, {
    source: "https://images.example.com/a.png",
    onRequest: () => { calls++; return new Promise(done => { resolve = done; }); },
  });
  const button = fixture.last("button");
  const first = button.fire("click");
  await button.fire("click");
  assert.equal(calls, 1);
  resolve(true);
  await first;
  assert.ok(fixture.last("img"));

  const denied = documentFixture();
  const control = onlineImageControl(denied.document, {
    source: "https://images.example.com/a.png", onRequest: () => { throw new Error("no permission"); },
  });
  await denied.last("button").fire("click");
  assert.equal(control.dataset.onlineImageState, "error");
  assert.equal(denied.last("img"), undefined);
  assert.equal(denied.last("button").disabled, undefined);
});
