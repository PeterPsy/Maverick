import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import vm from "node:vm";

const bodies = new Map([
  ["/", "shell"],
  ["/offline.html", "offline-document"],
  ["/apps/base-shell/assets/index-testhash.js", "immutable-bundle"],
]);
const records = [...bodies].map(([url, body]) => ({
  url,
  path: url === "/" ? "index.html" : url.slice(1),
  sha256: createHash("sha256").update(body).digest("hex"),
  size_bytes: Buffer.byteLength(body),
}));

test("precache installation is atomic and keeps the previous build after interruption", async () => {
  const harness = workerHarness();
  await harness.caches.open("maverick-static-v2:previous");
  harness.fetchImpl = async (input) => {
    const path = requestPath(input);
    if (path === "/offline.html") throw new Error("network interrupted");
    return responseFor(path);
  };

  await assert.rejects(harness.internals.installPrecache(), /network interrupted/);
  assert.ok((await harness.caches.keys()).includes("maverick-static-v2:previous"));
  assert.ok(!(await harness.caches.keys()).includes(harness.internals.STATIC_CACHE_NAME));

  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.internals.installPrecache();
  const cache = await harness.caches.open(harness.internals.STATIC_CACHE_NAME);
  for (const record of records) assert.ok(await cache.match(record.url));
});

test("an update waits behind the active worker until the shell explicitly accepts it", async () => {
  const harness = workerHarness({ activeWorker: {} });
  harness.fetchImpl = async (input) => responseFor(requestPath(input));

  await harness.dispatchExtendable("install");
  assert.equal(harness.skipWaitingCalls, 0);
  await harness.dispatchExtendable("message", { data: { type: "MAVERICK_SKIP_WAITING" } });
  assert.equal(harness.skipWaitingCalls, 1);
});

test("offline navigation reopens the shell and gives uncached apps a contextual document", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.internals.installPrecache();
  harness.fetchImpl = async () => { throw new TypeError("offline"); };

  const shell = await harness.internals.navigationFallback(fakeRequest("/app/chat", "navigate"), new URL("https://maverick.test/app/chat"));
  const app = await harness.internals.navigationFallback(fakeRequest("/apps/chat/", "navigate"), new URL("https://maverick.test/apps/chat/"));

  assert.equal(await shell.text(), "shell");
  assert.equal(await app.text(), "offline-document");
});

test("temporary server errors use the same verified navigation fallback", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.internals.installPrecache();
  harness.fetchImpl = async () => new Response("temporary failure", { status: 503 });

  const response = await harness.internals.navigationFallback(fakeRequest("/", "navigate"), new URL("https://maverick.test/"));

  assert.equal(await response.text(), "shell");
});

test("a corrupted verified shell entry is deleted and repaired from the network", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.internals.installPrecache();
  const record = records.find(({ url }) => url.includes("index-testhash.js"));
  const cache = await harness.caches.open(harness.internals.STATIC_CACHE_NAME);
  await cache.put(record.url, new Response("corrupt", { status: 200 }));

  const repaired = await harness.internals.cacheFirstVerifiedShellAsset(fakeRequest(record.url), record);

  assert.equal(await repaired.text(), bodies.get(record.url));
  assert.equal(await (await cache.match(record.url)).text(), bodies.get(record.url));
});

test("recovery preserves verified entries when a missing entry cannot be fetched", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.internals.installPrecache();
  const cache = await harness.caches.open(harness.internals.STATIC_CACHE_NAME);
  await cache.delete("/offline.html");
  harness.fetchImpl = async (input) => {
    if (requestPath(input) === "/offline.html") throw new TypeError("offline");
    return responseFor(requestPath(input));
  };

  await assert.rejects(harness.internals.recoverPrecache(), /offline/);

  assert.equal(await (await cache.match("/")).text(), "shell");
  assert.equal(await cache.match("/offline.html"), undefined);
});

test("kill switch removes only known Maverick static caches and unregisters", async () => {
  const harness = workerHarness();
  await Promise.all([
    harness.caches.open(harness.internals.STATIC_CACHE_NAME),
    harness.caches.open("maverick-static-v2:old"),
    harness.caches.open("maverick-base-shell-v3"),
    harness.caches.open("maverick-app-static-v2"),
    harness.caches.open("another-app-cache"),
  ]);

  await harness.dispatchExtendable("message", { data: { type: "MAVERICK_DISABLE" } });

  assert.deepEqual(await harness.caches.keys(), ["another-app-cache"]);
  assert.equal(harness.unregisterCalls, 1);
});

test("API, SSE, backend, sidecar and worker requests are never intercepted", () => {
  const harness = workerHarness();
  for (const [path, accept = ""] of [
    ["/api/session"],
    ["/api/apps/events", "text/event-stream"],
    ["/apps/chat/backend"],
    ["/apps/design-studio/sidecar/project"],
    ["/apps/design-studio/sidecar"],
    ["/ws"],
    ["/sw.js"],
  ]) {
    const request = fakeRequest(path, "cors", accept);
    assert.equal(harness.internals.isExcludedRequest(request, new URL(request.url)), true, path);
  }
  const rangeRequest = fakeRequest("/apps/base-shell/assets/index-testhash.js", "cors", "", { Range: "bytes=0-3" });
  assert.equal(harness.internals.isExcludedRequest(rangeRequest, new URL(rangeRequest.url)), true, "range request");
});

test("visited app runtime cache accepts only core-verified immutable static responses", async () => {
  const harness = workerHarness();
  let fetches = 0;
  harness.fetchImpl = async () => {
    fetches += 1;
    return new Response("app-bundle", {
      status: 200,
      headers: {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Type": "application/javascript",
      },
    });
  };
  const request = fakeRequest("/apps/chat/assets/app-contenthash.js");

  assert.equal(await (await harness.internals.visitedAppStaticAsset(request)).text(), "app-bundle");
  assert.equal(await (await harness.internals.visitedAppStaticAsset(request)).text(), "app-bundle");
  assert.equal(fetches, 1);

  const cache = await harness.caches.open(harness.internals.APP_STATIC_CACHE_NAME);
  await cache.put(request, new Response("poisoned-html", { status: 200, headers: { "Content-Type": "text/html" } }));
  assert.equal(await (await harness.internals.visitedAppStaticAsset(request)).text(), "app-bundle");
  assert.equal(fetches, 2);

  const mutable = new Response("mutable", { status: 200, headers: { "Cache-Control": "public, max-age=60" } });
  assert.equal(harness.internals.responseCanEnterAppStaticCache(mutable), false);
});

test("activation cleans obsolete static builds without touching runtime or unrelated caches", async () => {
  const harness = workerHarness();
  await Promise.all([
    harness.caches.open(harness.internals.STATIC_CACHE_NAME),
    harness.caches.open("maverick-static-v2:old"),
    harness.caches.open("maverick-base-shell-v3"),
    harness.caches.open("maverick-app-static-v2"),
    harness.caches.open("unrelated-cache"),
  ]);

  await harness.dispatchExtendable("activate");

  assert.deepEqual((await harness.caches.keys()).sort(), [harness.internals.STATIC_CACHE_NAME, "maverick-app-static-v2", "unrelated-cache"].sort());
  assert.equal(harness.claimCalls, 1);
});

function workerHarness({ activeWorker = null } = {}) {
  const listeners = new Map();
  const caches = new MemoryCacheStorage();
  const harness = {
    caches,
    claimCalls: 0,
    fetchImpl: async (input) => responseFor(requestPath(input)),
    skipWaitingCalls: 0,
    unregisterCalls: 0,
  };
  const self = {
    addEventListener(type, listener) { listeners.set(type, listener); },
    clients: {
      async claim() { harness.claimCalls += 1; },
      async matchAll() { return []; },
    },
    location: { origin: "https://maverick.test" },
    registration: {
      active: activeWorker,
      async unregister() { harness.unregisterCalls += 1; return true; },
    },
    async skipWaiting() { harness.skipWaitingCalls += 1; },
  };
  let source = readFileSync(resolve(import.meta.dirname, "../frontend/public/sw.js"), "utf8");
  source = source
    .replaceAll("__MAVERICK_BUILD_ID__", "test-build")
    .replaceAll("__MAVERICK_PRECACHE_MANIFEST__", JSON.stringify(records))
    .replaceAll("__MAVERICK_IMMUTABLE_ASSETS__", JSON.stringify([records[2]]));
  source += `\nself.__MAVERICK_SW_INTERNALS__ = {
    APP_STATIC_CACHE_NAME,
    BUILD_ID,
    STATIC_CACHE_NAME,
    cacheFirstVerifiedShellAsset,
    deleteKnownStaticCaches,
    installPrecache,
    isExcludedRequest,
    navigationFallback,
    recoverPrecache,
    responseCanEnterAppStaticCache,
    responseMatchesRecord,
    visitedAppStaticAsset,
  };\n`;
  vm.runInNewContext(source, {
    AbortController,
    Error,
    Headers,
    Map,
    Promise,
    Request,
    Response,
    Set,
    TypeError,
    URL,
    Uint8Array,
    caches,
    clearTimeout,
    console,
    crypto: webcrypto,
    fetch: (...args) => harness.fetchImpl(...args),
    self,
    setTimeout,
  });
  harness.internals = self.__MAVERICK_SW_INTERNALS__;
  harness.dispatchExtendable = async (type, values = {}) => {
    let pending = Promise.resolve();
    const event = {
      ...values,
      source: values.source || { postMessage() {} },
      waitUntil(value) { pending = Promise.resolve(value); },
    };
    listeners.get(type)(event);
    await pending;
  };
  return harness;
}

class MemoryCacheStorage {
  constructor() { this.stores = new Map(); }
  async delete(name) { return this.stores.delete(name); }
  async keys() { return [...this.stores.keys()]; }
  async open(name) {
    if (!this.stores.has(name)) this.stores.set(name, new MemoryCache());
    return this.stores.get(name);
  }
}

class MemoryCache {
  constructor() { this.responses = new Map(); }
  async delete(request) { return this.responses.delete(requestPath(request)); }
  async match(request) { return this.responses.get(requestPath(request))?.clone() || undefined; }
  async put(request, response) { this.responses.set(requestPath(request), response.clone()); }
}

function fakeRequest(path, mode = "cors", accept = "", headers = {}) {
  return {
    headers: new Headers({ ...headers, ...(accept ? { Accept: accept } : {}) }),
    method: "GET",
    mode,
    url: `https://maverick.test${path}`,
  };
}

function requestPath(input) {
  const value = typeof input === "string" ? input : input.url;
  return new URL(value, "https://maverick.test").pathname;
}

function responseFor(path) {
  const body = bodies.get(path);
  if (body === undefined) return new Response("not found", { status: 404 });
  return new Response(body, { status: 200, headers: { "Content-Type": path.endsWith(".js") ? "application/javascript" : "text/html" } });
}
