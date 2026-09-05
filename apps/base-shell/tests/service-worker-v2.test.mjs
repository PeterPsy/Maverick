import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import vm from "node:vm";

const bodies = new Map([
  ["/", "shell"],
  ["/favicon.ico", "icon"],
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
    if (path === "/favicon.ico") throw new Error("network interrupted");
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

test("network failure reopens only shell navigations from the verified standard entrypoint", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.internals.installPrecache();
  harness.fetchImpl = async () => { throw new TypeError("network unavailable"); };

  const shellResponse = harness.dispatchFetch(fakeRequest("/app/chat", "navigate"));
  const appResponse = harness.dispatchFetch(fakeRequest("/apps/chat/", "navigate"));

  assert.ok(shellResponse);
  assert.equal(await (await shellResponse).text(), "shell");
  assert.equal(appResponse, null, "non-shell navigation must retain normal browser handling");
});

test("a first shell visit without a verified fallback rejects instead of synthesizing product HTML", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async () => { throw new TypeError("network unavailable"); };

  await assert.rejects(
    harness.internals.navigationFallback(fakeRequest("/app/chat", "navigate")),
    /network unavailable/,
  );
});

test("temporary server errors use the same verified navigation fallback", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.internals.installPrecache();
  harness.fetchImpl = async () => new Response("temporary failure", { status: 503 });

  const response = await harness.internals.navigationFallback(fakeRequest("/", "navigate"));

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

test("shell Cache API write failures never replace valid network responses", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  const shellCache = await harness.caches.open(harness.internals.STATIC_CACHE_NAME);
  shellCache.writeError = quotaError();

  const immutableRecord = records.find(({ url }) => url.includes("index-testhash.js"));
  const immutable = await harness.internals.cacheFirstVerifiedShellAsset(fakeRequest(immutableRecord.url), immutableRecord);
  const revalidatedRecord = records.find(({ url }) => url === "/favicon.ico");
  const revalidated = await harness.internals.networkFirstPrecachedAsset(fakeRequest(revalidatedRecord.url), revalidatedRecord);

  assert.equal(await immutable.text(), bodies.get(immutableRecord.url));
  assert.equal(await revalidated.text(), bodies.get(revalidatedRecord.url));
});

test("recovery preserves verified entries when a missing entry cannot be fetched", async () => {
  const harness = workerHarness();
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.internals.installPrecache();
  const cache = await harness.caches.open(harness.internals.STATIC_CACHE_NAME);
  await cache.delete("/favicon.ico");
  harness.fetchImpl = async (input) => {
    if (requestPath(input) === "/favicon.ico") throw new TypeError("network unavailable");
    return responseFor(requestPath(input));
  };

  await assert.rejects(harness.internals.recoverPrecache(), /network unavailable/);

  assert.equal(await (await cache.match("/")).text(), "shell");
  assert.equal(await cache.match("/favicon.ico"), undefined);
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

test("app assets use the public HTTP cache instead of an unreachable shell Cache API", () => {
  const harness = workerHarness();
  const request = fakeRequest("/apps/chat/assets/app-contenthash.js");

  assert.equal(harness.dispatchFetch(request), null);
});

test("activation cleans obsolete shell and app-static caches without touching unrelated caches", async () => {
  const harness = workerHarness();
  await Promise.all([
    harness.caches.open(harness.internals.STATIC_CACHE_NAME),
    harness.caches.open("maverick-static-v2:old"),
    harness.caches.open("maverick-base-shell-v3"),
    harness.caches.open("maverick-app-static-v2"),
    harness.caches.open("unrelated-cache"),
  ]);

  await harness.dispatchExtendable("activate");

  assert.deepEqual((await harness.caches.keys()).sort(), [harness.internals.STATIC_CACHE_NAME, "unrelated-cache"].sort());
  assert.equal(harness.claimCalls, 1);
});

test("worker observability emits only closed redaction-safe metric names", async () => {
  const harness = workerHarness({ clientCount: 2 });
  harness.fetchImpl = async (input) => responseFor(requestPath(input));
  await harness.dispatchExtendable("install");
  const record = records.find(({ url }) => url.includes("index-testhash.js"));
  await harness.internals.cacheFirstVerifiedShellAsset(fakeRequest(record.url), record);
  await new Promise((resolve) => setTimeout(resolve, 0));

  const metrics = harness.clientMessages.filter((message) => message.type === "MAVERICK_PWA_METRIC");
  assert.ok(metrics.some((message) => message.metric === "pwa_sw_install"));
  assert.ok(metrics.some((message) => message.metric === "pwa_static_cache_hit"));
  for (const message of metrics) {
    assert.deepEqual(Object.keys(message).sort(), ["metric", "type"]);
    assert.doesNotMatch(JSON.stringify(message), /index-testhash|https?:|favicon|build/i);
  }
  assert.equal(
    harness.clientMessagesByClient.filter((messages) => messages.some((message) => message.type === "MAVERICK_PWA_METRIC")).length,
    1,
    "one worker event must be delivered to exactly one metrics collector",
  );
});

function workerHarness({ activeWorker = null, clientCount = 1 } = {}) {
  const listeners = new Map();
  const caches = new MemoryCacheStorage();
  const harness = {
    caches,
    claimCalls: 0,
    clientMessages: [],
    clientMessagesByClient: Array.from({ length: clientCount }, () => []),
    fetchImpl: async (input) => responseFor(requestPath(input)),
    skipWaitingCalls: 0,
    unregisterCalls: 0,
  };
  const self = {
    addEventListener(type, listener) { listeners.set(type, listener); },
    clients: {
      async claim() { harness.claimCalls += 1; },
      async matchAll() {
        return harness.clientMessagesByClient.map((messages) => ({
          postMessage(message) {
            messages.push(message);
            harness.clientMessages.push(message);
          },
        }));
      },
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
    .replaceAll("__MAVERICK_IMMUTABLE_ASSETS__", JSON.stringify([records[2]]))
    .replaceAll("__MAVERICK_NAVIGATION_FALLBACK_URL__", JSON.stringify("/"));
  source += `\nself.__MAVERICK_SW_INTERNALS__ = {
    BUILD_ID,
    STATIC_CACHE_NAME,
    cacheFirstVerifiedShellAsset,
    deleteKnownStaticCaches,
    installPrecache,
    isExcludedRequest,
    navigationFallback,
    networkFirstPrecachedAsset,
    recoverPrecache,
    responseMatchesRecord,
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
  harness.dispatchFetch = (request) => {
    let response = null;
    listeners.get("fetch")({
      request,
      respondWith(value) { response = Promise.resolve(value); },
    });
    return response;
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
  constructor() { this.responses = new Map(); this.writeError = null; }
  async delete(request) {
    if (this.writeError) throw this.writeError;
    return this.responses.delete(requestPath(request));
  }
  async match(request) { return this.responses.get(requestPath(request))?.clone() || undefined; }
  async put(request, response) {
    if (this.writeError) throw this.writeError;
    this.responses.set(requestPath(request), response.clone());
  }
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

function quotaError() {
  return Object.assign(new Error("Cache quota exceeded"), { name: "QuotaExceededError" });
}
