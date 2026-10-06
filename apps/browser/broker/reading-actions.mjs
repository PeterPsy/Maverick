// Fixed observations for rendered pages. No caller-supplied JavaScript or selectors.

export function readingOptions(action, payload) {
  if (action === "content.read") {
    return {
      maxChars: integer(payload.max_chars, 40_000, 1, 100_000, "max_chars"),
      maxItems: integer(payload.max_items, 100, 1, 200, "max_items"),
    };
  }
  if (action === "scroll") {
    const direction = payload.direction ?? "down";
    if (!["up", "down"].includes(direction)) {
      throw readingError("direction must be up or down.");
    }
    return {
      direction,
      pixels: integer(payload.pixels, 900, 1, 2000, "pixels"),
      steps: integer(payload.steps, 1, 1, 5, "steps"),
      settleMs: integer(payload.settle_ms, 500, 0, 1500, "settle_ms"),
    };
  }
  const time = payload.time_seconds;
  if (time !== undefined && (typeof time !== "number" || !Number.isFinite(time) || time < 0 || time > 86_400)) {
    throw readingError("time_seconds must be a finite number between 0 and 86400.");
  }
  return {
    videoIndex: integer(payload.video_index, 0, 0, 199, "video_index"),
    timeSeconds: time,
  };
}

export async function readContent(page, payload, redactUrl) {
  const options = readingOptions("content.read", payload);
  const result = await page.evaluate(collectRenderedContent, options);
  for (const item of result.links) item.url = redactUrl(item.url);
  for (const item of result.images) item.url = redactUrl(item.url);
  for (const item of result.videos) {
    if (item.url) item.url = redactUrl(item.url);
    if (item.poster_url) item.poster_url = redactUrl(item.poster_url);
  }
  return { ...result, observed_at: new Date().toISOString(), source: "rendered_dom" };
}

// Kept self-contained so Playwright serializes this exact function into the page.
export function collectRenderedContent({ maxChars, maxItems }) {
  const text = document.body?.innerText || "";
  const httpUrl = (value) => {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const url = new URL(value, document.baseURI);
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch {
      return null;
    }
  };
  const visible = (element) => {
    if (!element.getClientRects().length) return false;
    const style = getComputedStyle(element);
    return style.visibility !== "hidden" && style.display !== "none";
  };
  const links = [];
  const images = [];
  const videos = [];
  const seenLinks = new Set();
  const seenImages = new Set();
  let linksTotal = 0;
  let imagesTotal = 0;
  let videosTotal = 0;
  for (const element of document.querySelectorAll("a[href]")) {
    const url = httpUrl(element.href);
    if (!url || !visible(element) || seenLinks.has(url)) continue;
    seenLinks.add(url);
    linksTotal++;
    if (links.length < maxItems) links.push({ url, text: (element.innerText || element.getAttribute("aria-label") || "").slice(0, 1000) });
  }
  for (const element of document.querySelectorAll("img")) {
    const url = httpUrl(element.currentSrc || element.src);
    if (!url || !visible(element) || seenImages.has(url)) continue;
    seenImages.add(url);
    imagesTotal++;
    if (images.length < maxItems) images.push({ url, alt: (element.alt || "").slice(0, 1000), width: element.naturalWidth, height: element.naturalHeight });
  }
  const allVideos = document.querySelectorAll("video");
  for (let index = 0; index < allVideos.length; index++) {
    const element = allVideos[index];
    if (!visible(element)) continue;
    videosTotal++;
    if (index <= 199 && videos.length < maxItems) videos.push({
      video_index: index,
      url: httpUrl(element.currentSrc || element.src),
      poster_url: httpUrl(element.poster),
      duration_seconds: Number.isFinite(element.duration) ? element.duration : null,
      current_time_seconds: element.currentTime,
      width: element.videoWidth,
      height: element.videoHeight,
      ready_state: element.readyState,
    });
  }
  const root = document.scrollingElement;
  return {
    title: document.title.slice(0, 1000),
    language: document.documentElement.lang.slice(0, 100),
    text: text.slice(0, maxChars),
    text_truncated: text.length > maxChars,
    links, images, videos,
    totals: { links: linksTotal, images: imagesTotal, videos: videosTotal },
    items_truncated: linksTotal > links.length || imagesTotal > images.length || videosTotal > videos.length,
    scroll: { top: root?.scrollTop || 0, height: root?.scrollHeight || 0, viewport_height: root?.clientHeight || 0 },
    coverage: "Currently rendered page only; lazy-loaded and unvisited content is not included.",
  };
}

export async function scrollPage(page, payload) {
  const options = readingOptions("scroll", payload);
  const before = await page.evaluate(scrollPosition);
  for (let step = 0; step < options.steps; step++) {
    await page.evaluate((pixels) => {
      document.scrollingElement?.scrollBy({ top: pixels, behavior: "instant" });
    }, options.direction === "down" ? options.pixels : -options.pixels);
    if (options.settleMs) await page.waitForTimeout(options.settleMs);
  }
  const after = await page.evaluate(scrollPosition);
  return {
    before, after,
    moved: before.top !== after.top,
    at_bottom: after.top + after.viewport_height >= after.height - 1,
    coverage: "Viewport boundary only; at_bottom does not guarantee a complete infinite feed.",
  };
}

function scrollPosition() {
  const root = document.scrollingElement;
  return { top: root?.scrollTop || 0, height: root?.scrollHeight || 0, viewport_height: root?.clientHeight || 0 };
}

export async function videoFrame(page, payload) {
  const options = readingOptions("video.frame", payload);
  const video = page.locator("video").nth(options.videoIndex);
  if (!await video.count()) throw readingError("The selected video is not rendered on this page.", "video_unavailable", 404);
  const timing = await video.evaluate(async (element, time) => {
    const fail = (message) => ({ error: message });
    if (element.readyState < 2) return fail("The video has no decoded frame; open or load the video first.");
    element.pause();
    if (time !== null) {
      if (!Number.isFinite(element.duration) || time >= element.duration) return fail("The requested time is outside a finite video duration.");
      if (Math.abs(element.currentTime - time) > 0.001 || element.seeking) {
        const seeked = new Promise((resolve) => {
          const finish = (result) => {
            clearTimeout(timer);
            element.removeEventListener("seeked", onSeeked);
            element.removeEventListener("error", onError);
            resolve(result);
          };
          const onSeeked = () => finish(null);
          const onError = () => finish("Video seek failed.");
          const timer = setTimeout(() => finish("Video seek timed out."), 10_000);
          element.addEventListener("seeked", onSeeked, { once: true });
          element.addEventListener("error", onError, { once: true });
          try { element.currentTime = time; } catch { finish("Video seek failed."); }
        });
        const error = await seeked;
        if (error) return fail(error);
      }
    }
    if (element.readyState < 2) return fail("The requested frame has not decoded.");
    return { time_seconds: element.currentTime, duration_seconds: Number.isFinite(element.duration) ? element.duration : null };
  }, options.timeSeconds ?? null);
  if (timing.error) throw readingError(timing.error, "video_frame_unavailable", 422);
  const buffer = await video.screenshot({ type: "jpeg", quality: 80, timeout: 10_000 });
  return {
    video_index: options.videoIndex,
    ...timing,
    mime_type: "image/jpeg",
    encoding: "base64",
    data: buffer.toString("base64"),
    persisted: false,
    coverage: "One rendered video frame; no audio transcription or full-video analysis.",
  };
}

function integer(value, fallback, minimum, maximum, field) {
  if (value === undefined) return fallback;
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw readingError(`${field} must be an integer between ${minimum} and ${maximum}.`);
  }
  return value;
}

function readingError(message, code = "validation_error", statusCode = 400) {
  return Object.assign(new Error(message), { code, statusCode });
}
