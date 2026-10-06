globalThis.maverickBrowserRead=function collectRenderedContent({ maxChars, maxItems }) {
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
};
