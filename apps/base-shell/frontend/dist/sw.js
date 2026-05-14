const CACHE_NAME = "maverick-base-shell-v3";
const SHELL_ASSET_PREFIX = "/apps/base-shell/";
const SHELL_BUNDLE_PREFIX = `${SHELL_ASSET_PREFIX}assets/`;
const ROOT_SHELL_ASSETS = [
  "/manifest.webmanifest",
  "/apps/base-shell/app-icon-lightcolor-192.png",
  "/apps/base-shell/app-icon-lightcolor.png",
  "/apps/base-shell/pwa-maskable-light.png",
  "/apps/base-shell/pwa-apple-touch-icon.png",
  "/apps/base-shell/maverick-mark.svg",
  "/apps/base-shell/maverick-logotype.svg",
  "/apps/base-shell/sidebar-logo.svg"
];
const SAFE_SHELL_FILES = new Set(ROOT_SHELL_ASSETS.filter((path) => path.startsWith(SHELL_ASSET_PREFIX)));

function isAuthenticatedOrDynamicPath(url) {
  return (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/app/") ||
    url.pathname === "/app" ||
    url.pathname.startsWith("/api/apps/") ||
    url.pathname.includes("/backend")
  );
}

function isSafeShellAsset(request, url) {
  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return false;
  }
  if (request.mode === "navigate" || isAuthenticatedOrDynamicPath(url)) {
    return false;
  }
  if (request.headers.get("accept")?.includes("text/event-stream")) {
    return false;
  }
  if (url.pathname === "/sw.js") {
    return false;
  }
  return url.pathname === "/manifest.webmanifest" || url.pathname.startsWith(SHELL_BUNDLE_PREFIX) || SAFE_SHELL_FILES.has(url.pathname);
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response.ok) {
      await cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
    throw error;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) {
    return cached;
  }
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(ROOT_SHELL_ASSETS))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (!isSafeShellAsset(request, url)) {
    return;
  }
  if (url.pathname.startsWith(SHELL_BUNDLE_PREFIX)) {
    event.respondWith(cacheFirst(request));
    return;
  }
  event.respondWith(networkFirst(request));
});
