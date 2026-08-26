#!/usr/bin/env node
/** Verify first install, full browser restart, offline shell, and confirmed reconnect. */

import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";

const requireFromChat = createRequire(new URL("../apps/chat/package.json", import.meta.url));
const { chromium, webkit } = requireFromChat("playwright");
const args = parseArgs(process.argv.slice(2));
const baseUrl = requiredArg(args, "base-url").replace(/\/$/, "");
const engine = String(args.engine || "chromium").toLowerCase();
const browserType = engine === "chromium" ? chromium : engine === "webkit" ? webkit : null;
const profileRoot = mkdtempSync(resolve(tmpdir(), "maverick-pwa-shell-"));

if (!browserType) {
  throw new Error("--engine must be chromium or webkit");
}
if (!/^https?:$/.test(new URL(baseUrl).protocol)) {
  throw new Error("--base-url must use http or https");
}

let firstContext;
let restartedContext;
try {
  try {
    firstContext = await launchPersistentContext();
  } catch (error) {
    emit({
      schema: "maverick.pwa-shell-smoke.v1",
      skipped: true,
      engine,
      reason: `browser unavailable: ${safeError(error)}`,
    });
    rmSync(profileRoot, { force: true, recursive: true });
    process.exitCode = 0;
    process.exit();
  }

  const firstPage = firstContext.pages()[0] || await firstContext.newPage();
  await firstPage.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await firstPage.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await firstPage.waitForFunction(() => Boolean(navigator.serviceWorker.controller), null, { timeout: 15_000 });
  const install = await firstPage.evaluate(async () => {
    const manifestResponse = await fetch("/apps/base-shell/maverick-frontend-assets.json", { cache: "no-store" });
    if (!manifestResponse.ok) throw new Error(`asset manifest HTTP ${manifestResponse.status}`);
    const manifest = await manifestResponse.json();
    const expectedCache = `maverick-static-v2:${manifest.build_id}`;
    const cache = await caches.open(expectedCache);
    const missing = [];
    for (const record of manifest.precache || []) {
      if (!(await cache.match(record.url))) missing.push(record.url);
    }
    return {
      build_id: manifest.build_id,
      cache_present: (await caches.keys()).includes(expectedCache),
      missing_count: missing.length,
      precache_count: (manifest.precache || []).length,
      worker_controlled: Boolean(navigator.serviceWorker.controller),
    };
  });
  assert(install.worker_controlled, "first online install did not acquire a controller");
  assert(install.cache_present, "versioned shell cache was not created");
  assert(install.precache_count > 0, "generated precache manifest is empty");
  assert(install.missing_count === 0, "one or more generated precache records are missing");

  await firstContext.close();
  firstContext = null;

  restartedContext = await launchPersistentContext();
  for (const page of restartedContext.pages()) await page.close();
  await restartedContext.setOffline(true);
  const offlinePage = await restartedContext.newPage();
  const offlineResponse = await offlinePage.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded", timeout: 20_000 });
  await offlinePage.locator(".bs-offline-workspace-shell").waitFor({ state: "visible", timeout: 10_000 });
  const offline = await offlinePage.evaluate(async () => {
    const excluded = [];
    for (const [path, headers] of [
      ["/api/pwa/config", {}],
      ["/api/events", { Accept: "text/event-stream" }],
      ["/apps/example/backend", {}],
      ["/apps/example/sidecar", {}],
    ]) {
      try {
        await fetch(path, { headers });
        excluded.push(false);
      } catch {
        excluded.push(true);
      }
    }
    return {
      contextual_state: document.body.textContent.includes("Contenuto non disponibile sul dispositivo"),
      excluded_requests_failed_offline: excluded.every(Boolean),
      iframe_count: document.querySelectorAll("iframe").length,
      indicator_count: document.querySelectorAll(".bs-offline-indicator").length,
      marked_offline_count: document.querySelectorAll('[data-maverick-connectivity="offline"]').length,
      prompt_action_count: [...document.querySelectorAll("button, a")].filter((element) => /invia prompt|nuova chat/i.test(element.textContent || "")).length,
    };
  });
  assert(offlineResponse?.fromServiceWorker(), "offline restart was not served by the active worker");
  assert(offline.contextual_state, "offline restart did not show the contextual unavailable state");
  assert(offline.indicator_count === 1 && offline.marked_offline_count === 1, "offline restart must show exactly one global indicator");
  assert(offline.iframe_count === 0, "offline shell mounted an application frame");
  assert(offline.prompt_action_count === 0, "an online-only prompt action remained executable");
  assert(offline.excluded_requests_failed_offline, "an API, SSE, backend, or sidecar request was intercepted");

  await offlinePage.locator(".bs-offline-indicator").click();
  const dialog = offlinePage.getByRole("dialog", { name: "Contenuti sul dispositivo" });
  await dialog.waitFor({ state: "visible" });
  assert((await dialog.innerText()).includes("Nessun dato privato"), "local-content management omitted the M2 privacy boundary");

  let releaseRequests;
  const requestsReleased = new Promise((resolveGate) => { releaseRequests = resolveGate; });
  await restartedContext.route("**/api/**", async (route) => {
    await requestsReleased;
    await route.continue();
  });
  await restartedContext.setOffline(false);
  await offlinePage.locator('[data-maverick-connectivity="checking"]').waitFor({ state: "attached", timeout: 5_000 });
  releaseRequests();
  await offlinePage.locator(".bs-offline-indicator").waitFor({ state: "detached", timeout: 15_000 });

  emit({
    schema: "maverick.pwa-shell-smoke.v1",
    captured_at: new Date().toISOString(),
    engine,
    environment: "playwright-persistent-profile",
    real_safari_and_home_screen_required_for_release_gate: true,
    build_id: install.build_id,
    precache_count: install.precache_count,
    first_online_install: "passed",
    full_browser_restart_offline: "passed",
    excluded_dynamic_requests: "passed",
    confirmed_reconnect: "passed",
  });
} finally {
  await firstContext?.close().catch(() => undefined);
  await restartedContext?.close().catch(() => undefined);
  rmSync(profileRoot, { force: true, recursive: true });
}

function launchPersistentContext() {
  const launchOptions = { headless: true };
  if (engine === "chromium") launchOptions.executablePath = discoverChromiumExecutablePath();
  return browserType.launchPersistentContext(profileRoot, launchOptions);
}

function discoverChromiumExecutablePath() {
  const configured = process.env.MAVERICK_PLAYWRIGHT_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (configured && existsSync(configured)) return configured;
  for (const candidate of ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"]) {
    if (existsSync(candidate)) return candidate;
  }
  const cacheRoot = join(homedir(), ".cache", "ms-playwright");
  if (existsSync(cacheRoot)) {
    for (const directory of readdirSync(cacheRoot).filter((name) => name.startsWith("chromium-")).sort().reverse()) {
      const candidate = join(cacheRoot, directory, "chrome-linux", "chrome");
      if (existsSync(candidate)) return candidate;
    }
  }
  return undefined;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) parsed[key] = true;
    else { parsed[key] = value; index += 1; }
  }
  return parsed;
}

function requiredArg(parsed, key) {
  const value = parsed[key];
  if (!value || value === true) throw new Error(`--${key} is required`);
  return String(value);
}

function safeError(error) {
  return (error instanceof Error ? error.message : String(error)).split("\n")[0].slice(0, 240);
}

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}
