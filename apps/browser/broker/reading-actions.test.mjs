import assert from "node:assert/strict";
import { test } from "node:test";
import { collectRenderedContent, readContent, readingOptions, scrollPage, videoFrame } from "./reading-actions.mjs";

test("reading operations reject oversized, fractional, boolean and nonfinite inputs", () => {
  for (const [action, payload] of [
    ["content.read", { max_chars: 100001 }],
    ["content.read", { max_items: true }],
    ["scroll", { pixels: 1.5 }],
    ["scroll", { steps: 6 }],
    ["scroll", { direction: "left" }],
    ["video.frame", { time_seconds: Infinity }],
    ["video.frame", { time_seconds: null }],
    ["video.frame", { video_index: -1 }],
  ]) assert.throws(() => readingOptions(action, payload), { code: "validation_error" });
});

test("rendered extraction filters executable URLs, hidden nodes and duplicates", () => {
  const element = (properties, hidden = false) => ({
    getClientRects: () => hidden ? [] : [{}], getAttribute: () => null, ...properties,
  });
  const oldDocument = globalThis.document;
  const oldComputedStyle = globalThis.getComputedStyle;
  globalThis.getComputedStyle = () => ({ visibility: "visible", display: "block" });
  globalThis.document = {
    title: "Profile", baseURI: "https://example.com/profile", documentElement: { lang: "it" },
    body: { innerText: "Visible text, excluding form input values." },
    scrollingElement: { scrollTop: 0, scrollHeight: 3000, clientHeight: 900 },
    querySelectorAll: (selector) => ({
      "a[href]": [
        element({ href: "https://example.com/p/one", innerText: "Post one" }),
        element({ href: "https://example.com/p/one", innerText: "Duplicate" }),
        element({ href: "javascript:alert(1)" }),
        element({ href: "https://user:password@example.com/" }),
        element({ href: "https://example.com/hidden" }, true),
        element({ href: "https://example.com/p/two", innerText: "Post two" }),
      ],
      img: [element({ src: "data:image/png;base64,x" }), element({ src: "https://example.com/photo.jpg", alt: "Snow", naturalWidth: 100, naturalHeight: 150 })],
      video: [element({ src: "blob:video", poster: "", duration: Infinity, currentTime: 0, videoWidth: 0, videoHeight: 0, readyState: 0 })],
    })[selector],
  };
  try {
    const result = collectRenderedContent({ maxChars: 7, maxItems: 1 });
    assert.equal(result.text, "Visible");
    assert.equal(result.text_truncated, true);
    assert.equal(result.items_truncated, true);
    assert.equal(result.totals.links, 2);
    assert.equal(result.links.length, 1);
    assert.equal(result.images[0].alt, "Snow");
    assert.equal(result.videos[0].url, null);
    assert.equal(result.videos[0].poster_url, null);
    assert.equal(result.videos[0].duration_seconds, null);
  } finally {
    globalThis.document = oldDocument;
    globalThis.getComputedStyle = oldComputedStyle;
  }
});

test("content output never exposes signed URL query strings", async () => {
  const page = { evaluate: async () => ({ links: [{ url: "https://example.com/p?q=private" }], images: [{ url: "https://example.com/img?token=secret" }], videos: [{ url: "https://example.com/video?key=secret", poster_url: null }] }) };
  const redact = (value) => { const url = new URL(value); url.search = ""; return url.href; };
  const result = await readContent(page, {}, redact);
  assert.equal(result.images[0].url, "https://example.com/img");
  assert.equal(result.videos[0].url, "https://example.com/video");
  assert.equal(result.source, "rendered_dom");
});

test("video metadata never advertises an index outside the frame tool's supported range", () => {
  const previous = { document: globalThis.document, style: globalThis.getComputedStyle };
  const hidden = { getClientRects: () => [] };
  const visible = { getClientRects: () => [{}] };
  globalThis.getComputedStyle = () => ({ visibility: "visible", display: "block" });
  globalThis.document = {
    title: "", body: { innerText: "" }, documentElement: { lang: "" },
    querySelectorAll: selector => selector === "video" ? [...Array(200).fill(hidden), visible] : [],
  };
  try {
    const result = collectRenderedContent({ maxChars: 100, maxItems: 200 });
    assert.equal(result.totals.videos, 1);
    assert.deepEqual(result.videos, []);
    assert.equal(result.items_truncated, true);
  } finally {
    globalThis.document = previous.document;
    globalThis.getComputedStyle = previous.style;
  }
});

test("scroll takes bounded steps and distinguishes a viewport boundary from complete coverage", async () => {
  const positions = [{ top: 0, height: 1000, viewport_height: 500 }, { top: 500, height: 1000, viewport_height: 500 }];
  const scrolls = [], waits = [];
  const page = { evaluate: async (_fn, arg) => arg === undefined ? positions.shift() : scrolls.push(arg), waitForTimeout: async (ms) => waits.push(ms) };
  const result = await scrollPage(page, { steps: 2, pixels: 300, settle_ms: 10 });
  assert.deepEqual(scrolls, [300, 300]);
  assert.deepEqual(waits, [10, 10]);
  assert.equal(result.moved, true);
  assert.equal(result.at_bottom, true);
  assert.match(result.coverage, /does not guarantee/);
});

test("video capture returns observed timing and no frame for unavailable media", async () => {
  const missing = { count: async () => 0 };
  await assert.rejects(videoFrame({ locator: () => ({ nth: () => missing }) }, {}), { code: "video_unavailable" });
  const video = { count: async () => 1, evaluate: async () => ({ time_seconds: 2, duration_seconds: 10 }), screenshot: async () => Buffer.from("jpeg") };
  const result = await videoFrame({ locator: () => ({ nth: () => video }) }, { time_seconds: 2 });
  assert.equal(result.time_seconds, 2);
  assert.equal(result.persisted, false);
  assert.equal(Buffer.from(result.data, "base64").toString(), "jpeg");
  video.evaluate = async () => ({ error: "The video has no decoded frame." });
  await assert.rejects(videoFrame({ locator: () => ({ nth: () => video }) }, {}), { code: "video_frame_unavailable" });
});
