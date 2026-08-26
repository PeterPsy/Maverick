"use strict";

const BUILD_ID = "__MAVERICK_BUILD_ID__";
const PRECACHE = __MAVERICK_PRECACHE_MANIFEST__;
const IMMUTABLE_SHELL_ASSETS = __MAVERICK_IMMUTABLE_ASSETS__;
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
  const cached = await cache.match(record.url);
  if (!cached) {
    return null;
  }
  if (await responseMatchesRecord(cached, record)) {
    return cached;
  }
  await cache.delete(record.url);
  return null;
}

async function cacheFirstVerifiedShellAsset(request, record) {
  const cache = await caches.open(STATIC_CACHE_NAME);
  const cached = await verifiedCachedRecord(cache, record);
  if (cached) {
    return cached;
  }
  const response = await fetchVerifiedRecord(record, request);
  await cache.put(record.url, response.clone());
  return response;
}

async function networkFirstPrecachedAsset(request, record) {
  const cache = await caches.open(STATIC_CACHE_NAME);
  try {
    const response = await fetchVerifiedRecord(record, request);
    await cache.put(record.url, response.clone());
    return response;
  } catch (error) {
    const cached = await verifiedCachedRecord(cache, record);
    if (cached) {
      return cached;
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
  const cache = await caches.open(APP_STATIC_CACHE_NAME);
  const cached = await cache.match(request);
  if (cached && responseCanEnterAppStaticCache(cached)) {
    return cached;
  }
  if (cached) await cache.delete(request);
  const response = await fetch(request);
  if (responseCanEnterAppStaticCache(response)) {
    await cache.put(request, response.clone());
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
