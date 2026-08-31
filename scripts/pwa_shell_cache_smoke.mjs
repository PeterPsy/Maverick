#!/usr/bin/env node
/** Verify transparent standard-shell reuse and recovery after transport loss. */

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
const username = optionalArg(args, "username");
const password = optionalArg(args, "password");
const profileRoot = mkdtempSync(resolve(tmpdir(), "maverick-pwa-shell-"));

if (!browserType) {
  throw new Error("--engine must be chromium or webkit");
}
if (!/^https?:$/.test(new URL(baseUrl).protocol)) {
  throw new Error("--base-url must use http or https");
}
if (Boolean(username) !== Boolean(password)) {
  throw new Error("--username and --password must be provided together");
}

let firstContext;
let restartedContext;
try {
  try {
    firstContext = await launchPersistentContext();
  } catch (error) {
    emit({
      schema: "maverick.pwa-shell-cache-smoke.v2",
      skipped: true,
      engine,
      reason: `browser unavailable: ${safeError(error)}`,
    });
    rmSync(profileRoot, { force: true, recursive: true });
    process.exitCode = 0;
    process.exit();
  }

  if (username && password) {
    await authenticate(firstContext, username, password);
  }
  const firstPage = firstContext.pages()[0] || await firstContext.newPage();
  await firstPage.goto(`${baseUrl}${username ? "/app/chat" : "/"}`, {
    waitUntil: "domcontentloaded",
    timeout: 30_000,
  });
  await firstPage.locator("main.bs-shell, main.bs-login").waitFor({ state: "visible", timeout: 30_000 });
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
    const fallbackSelected = (manifest.precache || []).some(
      (record) => record.path === manifest.navigation_fallback,
    );
    return {
      build_id: manifest.build_id,
      cache_present: (await caches.keys()).includes(expectedCache),
      fallback_selected: fallbackSelected,
      manifest_schema: manifest.schema,
      missing_count: missing.length,
      navigation_fallback: manifest.navigation_fallback,
      precache_count: (manifest.precache || []).length,
      worker_controlled: Boolean(navigator.serviceWorker.controller),
    };
  });
  assert(install.manifest_schema === "maverick.frontend-assets.v2", "asset manifest is not schema v2");
  assert(install.navigation_fallback === "index.html", "navigation fallback is not the standard entrypoint");
  assert(install.fallback_selected, "standard navigation fallback is not selected for precache");
  assert(install.worker_controlled, "first online install did not acquire a controller");
  assert(install.cache_present, "versioned shell cache was not created");
  assert(install.precache_count > 0, "generated precache manifest is empty");
  assert(install.missing_count === 0, "one or more generated precache records are missing");

  const beforeTransportLoss = await standardTreeSnapshot(firstPage);
  if (username) {
    assert(beforeTransportLoss.iframe_count > 0, "authenticated shell did not mount its application frame");
  }
  await firstContext.setOffline(true);
  await firstPage.waitForTimeout(250);
  const duringTransportLoss = await standardTreeSnapshot(firstPage);
  assert(duringTransportLoss.root_class === beforeTransportLoss.root_class, "transport loss replaced the standard shell root");
  assert(duringTransportLoss.iframe_count === beforeTransportLoss.iframe_count, "transport loss changed the mounted frame tree");
  assert(duringTransportLoss.legacy_marker_count === 0, "transport loss rendered a superseded connectivity mode marker");
  await firstContext.setOffline(false);
  await firstPage.waitForTimeout(100);

  await firstContext.close();
  firstContext = null;

  restartedContext = await launchPersistentContext();
  for (const page of restartedContext.pages()) await page.close();
  await restartedContext.setOffline(true);
  const unavailablePage = await restartedContext.newPage();
  const unavailableResponse = await unavailablePage.goto(`${baseUrl}/`, {
    waitUntil: "domcontentloaded",
    timeout: 20_000,
  });
  await unavailablePage.locator("main.bs-shell").waitFor({ state: "visible", timeout: 10_000 });

  const unavailable = await unavailablePage.evaluate(async () => {
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
    const legacySelector = ".bs-offline-workspace-shell, .bs-offline-indicator, [data-maverick-connectivity]";
    return {
      excluded_requests_failed: excluded.every(Boolean),
      iframe_count: document.querySelectorAll("iframe").length,
      legacy_marker_count: document.querySelectorAll(legacySelector).length,
      loading_indicator_count: document.querySelectorAll('[aria-label="Loading workspace"]').length,
      standard_shell_count: document.querySelectorAll("main.bs-shell").length,
      superseded_copy_present: /Contenuto non disponibile sul dispositivo|Contenuti sul dispositivo/.test(document.body.textContent || ""),
    };
  });
  assert(unavailableResponse?.fromServiceWorker(), "standard-shell restart was not served by the active worker");
  assert(unavailable.standard_shell_count === 1, "restart did not render the standard shell entrypoint");
  assert(unavailable.loading_indicator_count === 1, "network-backed bootstrap did not remain in normal loading");
  assert(unavailable.legacy_marker_count === 0 && !unavailable.superseded_copy_present, "restart rendered superseded mode UI");
  assert(unavailable.excluded_requests_failed, "an API, SSE, backend, or sidecar request was intercepted");

  const nonShellPage = await restartedContext.newPage();
  let nonShellResponse = null;
  try {
    nonShellResponse = await nonShellPage.goto(`${baseUrl}/apps/chat/`, {
      waitUntil: "domcontentloaded",
      timeout: 5_000,
    });
  } catch {
    // Expected: non-shell navigations retain browser/network failure semantics.
  }
  assert(!nonShellResponse?.fromServiceWorker(), "a non-shell navigation received a service-worker fallback");
  await nonShellPage.close();

  const sessionResponse = unavailablePage.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/session" && response.status() < 500,
    { timeout: 20_000 },
  );
  await restartedContext.setOffline(false);
  await sessionResponse;
  await unavailablePage.waitForFunction(
    () => !document.querySelector('[aria-label="Loading workspace"]')
      && Boolean(document.querySelector(".bs-workspace-view-shell, main.bs-login")),
    null,
    { timeout: 20_000 },
  );
  const recovered = await standardTreeSnapshot(unavailablePage);
  assert(recovered.legacy_marker_count === 0, "transport recovery rendered a mode indicator");

  emit({
    schema: "maverick.pwa-shell-cache-smoke.v2",
    captured_at: new Date().toISOString(),
    engine,
    environment: "playwright-persistent-profile",
    real_safari_and_home_screen_required_for_release_gate: true,
    build_id: install.build_id,
    precache_count: install.precache_count,
    first_online_install: "passed",
    mounted_tree_preserved_during_transport_loss: "passed",
    standard_shell_restart_without_network: "passed",
    non_shell_navigation_bypass: "passed",
    excluded_dynamic_requests: "passed",
    transparent_transport_recovery: "passed",
    superseded_mode_ui_absent: "passed",
  });
} finally {
  await firstContext?.close().catch(() => undefined);
  await restartedContext?.close().catch(() => undefined);
  rmSync(profileRoot, { force: true, recursive: true });
}

async function authenticate(context, credential, secret) {
  const response = await context.request.post(`${baseUrl}/api/auth/login`, {
    data: { username: credential, password: secret },
  });
  if (!response.ok()) {
    throw new Error(`login failed with HTTP ${response.status()}`);
  }
}

async function standardTreeSnapshot(page) {
  return page.evaluate(() => {
    const root = document.querySelector("main.bs-shell, main.bs-login");
    return {
      iframe_count: document.querySelectorAll("iframe").length,
      legacy_marker_count: document.querySelectorAll(
        ".bs-offline-workspace-shell, .bs-offline-indicator, [data-maverick-connectivity]",
      ).length,
      root_class: root?.className || "",
    };
  });
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

function optionalArg(parsed, key) {
  const value = parsed[key];
  return value && value !== true ? String(value) : null;
}

function safeError(error) {
  return (error instanceof Error ? error.message : String(error)).split("\n")[0].slice(0, 240);
}

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}
