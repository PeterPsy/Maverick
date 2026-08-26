"use strict";

const BUILD_ID = "4f11e81e545a57882cb6997ece507fcf33a8ff326be7a0ab63d2ce3c7aba2c7d";
const PRECACHE = [{"url":"/","path":"index.html","sha256":"fe8d6fed37fefb57356390811a4f9215afe35383afabb38758503af54dad3d04","size_bytes":1977},{"url":"/apps/base-shell/app-icon-lightcolor.png","path":"app-icon-lightcolor.png","sha256":"5d3a4f9ec4e7a25ae7b12a09c6a7c0227239dd988427b5d232597718c25388b0","size_bytes":95846},{"url":"/apps/base-shell/assets/index-B3FYq0tq.css","path":"assets/index-B3FYq0tq.css","sha256":"45ad73f1e01819599cb5491e859652f4d15dfcd3cd575a6445986261447cd91f","size_bytes":76237},{"url":"/apps/base-shell/assets/index-Bj5E9Rc3.js","path":"assets/index-Bj5E9Rc3.js","sha256":"45a9f73b282af43a96328334a4a6ad31394382cf98f1cef4c0d2717cbdeb4a30","size_bytes":290610},{"url":"/apps/base-shell/assets/LoginPaperBackground-CKx83qyj.js","path":"assets/LoginPaperBackground-CKx83qyj.js","sha256":"0532b8ffc2d6f4fe9e5d6e28ff962b2ff8ad4ff0ebbd3abb2065269d8ab1a667","size_bytes":25087},{"url":"/apps/base-shell/maverick-logotype.svg","path":"maverick-logotype.svg","sha256":"1c539a4ff4a07b2c9bdb615137d7a0bb0f38669a51e182ae100dfe13816c3003","size_bytes":6739},{"url":"/apps/base-shell/maverick-mark.svg","path":"maverick-mark.svg","sha256":"443f449f6a75801128e8af19fd2fa29dca053c5161099d2d079f0f8704129983","size_bytes":17902},{"url":"/apps/base-shell/pwa-apple-touch-icon.png","path":"pwa-apple-touch-icon.png","sha256":"13d4ae0bc0542e428f17e78fb9692bb52c3d98b89d3b9b813dfe500b45b3e7eb","size_bytes":4075},{"url":"/apps/base-shell/pwa-logo-192.png","path":"pwa-logo-192.png","sha256":"d8e27d0f02f6f14aa7b0bfefd00390f498cfbf6a544ebdec3d7a6e73cd7cff24","size_bytes":4429},{"url":"/apps/base-shell/pwa-logo.png","path":"pwa-logo.png","sha256":"1d99b7bdf018ab1547f6f95c4bd27b857e2a488166b7569638cb70132feb9e10","size_bytes":16936},{"url":"/apps/base-shell/pwa-maskable-logo.png","path":"pwa-maskable-logo.png","sha256":"5507908977a5881cecfc719bca6168154648aaa6703ac8f5a078b57b34e18031","size_bytes":17394},{"url":"/apps/base-shell/sidebar-logo-black.svg","path":"sidebar-logo-black.svg","sha256":"e76119cb97a8066945b8fdc867767b1a7c8de1452214941308a8d1ec5058763f","size_bytes":6750},{"url":"/apps/base-shell/sidebar-logo.svg","path":"sidebar-logo.svg","sha256":"1c539a4ff4a07b2c9bdb615137d7a0bb0f38669a51e182ae100dfe13816c3003","size_bytes":6739},{"url":"/favicon.ico","path":"favicon.ico","sha256":"fd914dd9473a0d9cc495c1e1b3e31b2fddb611e28c428a8dc55ad99658f06912","size_bytes":270622},{"url":"/manifest.webmanifest","path":"manifest.webmanifest","sha256":"68094b835f2838d27849bd900f816e09370984de8c3646619c0b10ee3d5f5695","size_bytes":627},{"url":"/material-symbols-rounded.woff2","path":"material-symbols-rounded.woff2","sha256":"aa276a9d27fb7ecba87be04035fd664d0f1487f8b5638873586a795301b1cb97","size_bytes":414656},{"url":"/offline.html","path":"offline.html","sha256":"0b360ff456adb1814162c549b07344f7ab813149bb4f4aaf5cbcc8b818552cad","size_bytes":1961}];
const IMMUTABLE_SHELL_ASSETS = [{"url":"/apps/base-shell/assets/LoginPaperBackground-CKx83qyj.js","sha256":"0532b8ffc2d6f4fe9e5d6e28ff962b2ff8ad4ff0ebbd3abb2065269d8ab1a667","size_bytes":25087},{"url":"/apps/base-shell/assets/index-B3FYq0tq.css","sha256":"45ad73f1e01819599cb5491e859652f4d15dfcd3cd575a6445986261447cd91f","size_bytes":76237},{"url":"/apps/base-shell/assets/index-Bj5E9Rc3.js","sha256":"45a9f73b282af43a96328334a4a6ad31394382cf98f1cef4c0d2717cbdeb4a30","size_bytes":290610}];
const STATIC_CACHE_PREFIX = "maverick-static-v2:";
const STATIC_CACHE_NAME = `${STATIC_CACHE_PREFIX}${BUILD_ID}`;
const APP_STATIC_CACHE_NAME = "maverick-app-static-v2";
const LEGACY_STATIC_CACHE_NAMES = new Set(["maverick-base-shell-v3"]);
const SHELL_NAVIGATION_URL = "/";
const OFFLINE_DOCUMENT_URL = "/offline.html";
const NAVIGATION_TIMEOUT_MS = 5_000;
const PRECACHE_BY_URL = new Map(PRECACHE.map((record) => [record.url, record]));
const IMMUTABLE_BY_URL = new Map(IMMUTABLE_SHELL_ASSETS.map((record) => [record.url, record]));

function isExcludedRequest(request, url) {
  const accept = request.headers.get("accept") || "";
  return (
    request.method !== "GET" ||
    url.origin !== self.location.origin ||
    request.headers.has("range") ||
    accept.includes("text/event-stream") ||
    (url.pathname === "/api" || url.pathname.startsWith("/api/")) ||
    url.pathname === "/ws" ||
    url.pathname.startsWith("/ws/") ||
    /\/(?:backend|sidecar)(?:\/|$)/.test(url.pathname) ||
    url.pathname === "/sw.js"
  );
}

function isShellNavigation(url) {
  return url.pathname === "/" || url.pathname === "/app" || url.pathname.startsWith("/app/");
}

function isVisitedAppStaticAsset(url) {
  return url.pathname.startsWith("/apps/") && url.pathname.includes("/assets/") && !url.pathname.startsWith("/apps/base-shell/");
}

function responseCanEnterAppStaticCache(response) {
  const cacheControl = response.headers.get("cache-control") || "";
  const contentType = response.headers.get("content-type") || "";
  return (
    response.status === 200 &&
    !response.redirected &&
    (!response.url || new URL(response.url).origin === self.location.origin) &&
    ["basic", "default"].includes(response.type) &&
    !contentType.toLowerCase().includes("text/html") &&
    /(?:^|,)\s*public\b/i.test(cacheControl) &&
    /(?:^|,)\s*immutable\b/i.test(cacheControl) &&
    /(?:^|,)\s*max-age=31536000\b/i.test(cacheControl)
  );
}

async function sha256Hex(body) {
  const digest = await crypto.subtle.digest("SHA-256", body);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function responseMatchesRecord(response, record) {
  if (!response || !response.ok) {
    return false;
  }
  const body = await response.clone().arrayBuffer();
  return body.byteLength === record.size_bytes && (await sha256Hex(body)) === record.sha256;
}

async function fetchVerifiedRecord(record, request = record.url) {
  const response = await fetch(request, { cache: "reload", credentials: "same-origin" });
  if (!(await responseMatchesRecord(response, record))) {
    throw new Error(`Precache verification failed for ${record.url}`);
  }
  return response;
}

async function openCacheBestEffort(cacheName) {
  try {
    return await caches.open(cacheName);
  } catch {
    return null;
  }
}

async function matchCacheBestEffort(cache, request) {
  try {
    return await cache.match(request);
  } catch {
    return null;
  }
}

async function putCacheBestEffort(cache, request, response) {
  if (!cache) return;
  try {
    await cache.put(request, response.clone());
  } catch {
    // A valid network response must survive quota and Cache API failures.
  }
}

async function deleteCacheEntryBestEffort(cache, request) {
  try {
    await cache.delete(request);
  } catch {
    // A failed cleanup must not block the network path.
  }
}

async function installPrecache() {
  await caches.delete(STATIC_CACHE_NAME);
  const cache = await caches.open(STATIC_CACHE_NAME);
  try {
    for (const record of PRECACHE) {
      const response = await fetchVerifiedRecord(record);
      await cache.put(record.url, response.clone());
    }
  } catch (error) {
    await caches.delete(STATIC_CACHE_NAME);
    throw error;
  }
}

async function recoverPrecache() {
  const cache = await caches.open(STATIC_CACHE_NAME);
  for (const record of PRECACHE) {
    if (await verifiedCachedRecord(cache, record)) {
      continue;
    }
    const response = await fetchVerifiedRecord(record);
    await cache.put(record.url, response.clone());
  }
}

async function verifiedCachedRecord(cache, record) {
  const cached = await matchCacheBestEffort(cache, record.url);
  if (!cached) {
    return null;
  }
  try {
    if (await responseMatchesRecord(cached, record)) {
      return cached;
    }
  } catch {
    // Treat unreadable cache entries as misses and keep the network path alive.
  }
  await deleteCacheEntryBestEffort(cache, record.url);
  return null;
}

async function cacheFirstVerifiedShellAsset(request, record) {
  const cache = await openCacheBestEffort(STATIC_CACHE_NAME);
  if (cache) {
    const cached = await verifiedCachedRecord(cache, record);
    if (cached) {
      return cached;
    }
  }
  const response = await fetchVerifiedRecord(record, request);
  await putCacheBestEffort(cache, record.url, response);
  return response;
}

async function networkFirstPrecachedAsset(request, record) {
  const cache = await openCacheBestEffort(STATIC_CACHE_NAME);
  try {
    const response = await fetchVerifiedRecord(record, request);
    await putCacheBestEffort(cache, record.url, response);
    return response;
  } catch (error) {
    if (cache) {
      const cached = await verifiedCachedRecord(cache, record);
      if (cached) {
        return cached;
      }
    }
    throw error;
  }
}

async function navigationFallback(request, url) {
  try {
    const response = await fetchNavigationWithTimeout(request);
    if (response.status >= 500) {
      throw new Error(`Shell navigation failed with HTTP ${response.status}`);
    }
    return response;
  } catch {
    const fallbackUrl = isShellNavigation(url) ? SHELL_NAVIGATION_URL : OFFLINE_DOCUMENT_URL;
    const record = PRECACHE_BY_URL.get(fallbackUrl);
    if (record) {
      const cache = await caches.open(STATIC_CACHE_NAME);
      const cached = await verifiedCachedRecord(cache, record);
      if (cached) {
        return cached;
      }
    }
    return syntheticOfflineResponse();
  }
}

async function fetchNavigationWithTimeout(request) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), NAVIGATION_TIMEOUT_MS);
  try {
    return await fetch(request, { signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function visitedAppStaticAsset(request) {
  const cache = await openCacheBestEffort(APP_STATIC_CACHE_NAME);
  const cached = cache ? await matchCacheBestEffort(cache, request) : null;
  if (cached && responseCanEnterAppStaticCache(cached)) {
    return cached;
  }
  if (cached && cache) await deleteCacheEntryBestEffort(cache, request);
  const response = await fetch(request);
  if (responseCanEnterAppStaticCache(response)) {
    await putCacheBestEffort(cache, request, response);
  }
  return response;
}

function syntheticOfflineResponse() {
  return new Response(
    "<!doctype html><html lang=\"it\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>Maverick — rete non disponibile</title><body><main><h1>Contenuto non disponibile sul dispositivo</h1><p>La shell offline deve essere ripristinata con una connessione prima di mostrare questo contenuto.</p></main></body></html>",
    { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } },
  );
}

async function deleteKnownStaticCaches({ includeRuntime = false } = {}) {
  const keys = await caches.keys();
  const deletions = keys
    .filter((key) => key.startsWith(STATIC_CACHE_PREFIX) || LEGACY_STATIC_CACHE_NAMES.has(key) || (includeRuntime && key === APP_STATIC_CACHE_NAME))
    .map((key) => caches.delete(key));
  await Promise.all(deletions);
}

async function broadcast(message) {
  const clients = await self.clients.matchAll({ includeUncontrolled: true, type: "window" });
  clients.forEach((client) => client.postMessage(message));
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      await installPrecache();
      if (!self.registration.active) {
        await self.skipWaiting();
      }
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => (key.startsWith(STATIC_CACHE_PREFIX) || LEGACY_STATIC_CACHE_NAMES.has(key)) && key !== STATIC_CACHE_NAME)
          .map((key) => caches.delete(key)),
      );
      await self.clients.claim();
      await broadcast({ type: "MAVERICK_SW_ACTIVATED", build_id: BUILD_ID });
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (isExcludedRequest(request, url)) {
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(navigationFallback(request, url));
    return;
  }
  const immutableRecord = IMMUTABLE_BY_URL.get(url.pathname);
  if (immutableRecord) {
    event.respondWith(cacheFirstVerifiedShellAsset(request, immutableRecord));
    return;
  }
  const precacheRecord = PRECACHE_BY_URL.get(url.pathname);
  if (precacheRecord) {
    event.respondWith(networkFirstPrecachedAsset(request, precacheRecord));
    return;
  }
  if (isVisitedAppStaticAsset(url)) {
    event.respondWith(visitedAppStaticAsset(request));
  }
});

self.addEventListener("message", (event) => {
  const payload = event.data && typeof event.data === "object" ? event.data : {};
  if (payload.type === "MAVERICK_SKIP_WAITING") {
    event.waitUntil(self.skipWaiting());
    return;
  }
  if (payload.type === "MAVERICK_GET_VERSION") {
    event.source?.postMessage({ type: "MAVERICK_SW_VERSION", build_id: BUILD_ID });
    return;
  }
  if (payload.type === "MAVERICK_DISABLE") {
    event.waitUntil(
      (async () => {
        await deleteKnownStaticCaches({ includeRuntime: true });
        await self.registration.unregister();
        await broadcast({ type: "MAVERICK_SW_DISABLED", build_id: BUILD_ID });
      })(),
    );
    return;
  }
  if (payload.type === "MAVERICK_RECOVER") {
    event.waitUntil(
      (async () => {
        try {
          // Repair in place so a failed fetch never discards the already
          // verified entries that still make the active shell usable.
          await recoverPrecache();
          await broadcast({ type: "MAVERICK_SW_RECOVERED", build_id: BUILD_ID });
        } catch {
          await broadcast({ type: "MAVERICK_SW_RECOVERY_FAILED", build_id: BUILD_ID });
          throw new Error("Maverick static cache recovery failed.");
        }
      })(),
    );
  }
});
