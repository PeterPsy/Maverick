#!/usr/bin/env node
/** Capture redaction-safe cold, warm, file-revalidation, and transport-loss PWA metrics. */

import { existsSync, readdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";

const requireFromChat = createRequire(new URL("../apps/chat/package.json", import.meta.url));
const { chromium, devices, webkit } = requireFromChat("playwright");
const args = parseArgs(process.argv.slice(2));
const baseUrl = requiredArg(args, "base-url").replace(/\/$/, "");
const username = requiredArg(args, "username");
const password = requiredArg(args, "password");
const engineName = String(args.engine || "webkit").toLowerCase();
const runCount = boundedIntegerArg(args, "runs", 3, 1, 30);
const warmReloadCount = boundedIntegerArg(args, "warm-reloads", 1, 1, 10);
const fileUrl = optionalSameOriginUrl(args["file-url"]);
const browserType = engineName === "chromium" ? chromium : engineName === "webkit" ? webkit : null;

if (!browserType) {
  throw new Error("--engine must be webkit or chromium");
}

let browser;
try {
  const launchOptions = engineName === "chromium" ? { executablePath: discoverChromiumExecutablePath(), headless: true } : {};
  browser = await browserType.launch(launchOptions);
} catch (error) {
  emit({
    schema: "maverick.pwa-cache-baseline.v2",
    skipped: true,
    reason: `browser unavailable: ${safeError(error)}`,
  });
  process.exit(0);
}

try {
  const profiles = [
    ["mac-safari", devices["Desktop Safari"]],
    ["iphone-home-screen", devices["iPhone 15"]],
  ];
  const results = [];
  for (const [profileName, device] of profiles) {
    results.push(await measureProfile(profileName, device));
  }
  emit({
    schema: "maverick.pwa-cache-baseline.v2",
    captured_at: new Date().toISOString(),
    engine: engineName,
    environment: "playwright-emulation",
    real_device_required_for_release_gate: true,
    runs: runCount,
    warm_reloads: warmReloadCount,
    file_probe_configured: Boolean(fileUrl),
    profiles: results,
  });
} finally {
  await browser.close();
}

async function measureProfile(profile, device) {
  const samples = [];
  for (let run = 1; run <= runCount; run += 1) {
    const context = await browser.newContext(device);
    const page = await context.newPage();
    try {
      await authenticate(context);
      const cold = await measureNavigation(page, "cold", () => page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" }));
      const warm = [];
      for (let reload = 1; reload <= warmReloadCount; reload += 1) {
        warm.push(await measureNavigation(page, `warm-${reload}`, () => page.reload({ waitUntil: "domcontentloaded" })));
      }
      const file = fileUrl ? await measureFileRevalidation(context) : null;
      const networkUnavailable = await measureNetworkUnavailableReopen(context, page);
      samples.push({ run, cold, warm, file, network_unavailable_reopen: networkUnavailable });
    } finally {
      await context.close();
    }
  }
  return {
    profile,
    user_agent: String(device.userAgent || ""),
    samples,
    summary: summarize(samples),
  };
}

async function authenticate(context) {
  const response = await context.request.post(`${baseUrl}/api/auth/login`, {
    data: { username, password },
  });
  if (!response.ok()) {
    throw new Error(`login failed with HTTP ${response.status()}`);
  }
}

async function measureNavigation(page, phase, navigate) {
  const startedAt = performance.now();
  const metrics = emptyNavigationMetrics(phase);
  const pending = [];
  const onRequest = (request) => {
    if (request.resourceType() !== "websocket") {
      metrics.request_count += 1;
      if (!sameOrigin(request.url())) metrics.external_request_count += 1;
    }
  };
  const onResponse = (response) => {
    pending.push(recordResponse(metrics, response));
  };
  page.on("request", onRequest);
  page.on("response", onResponse);
  try {
    await navigate();
    await page.locator(".bs-shell").waitFor({ state: "visible", timeout: 30_000 });
    metrics.shell_visible_ms = Math.round(performance.now() - startedAt);
    await page.waitForTimeout(750);
    await Promise.allSettled(pending);
    metrics.total_ms = Math.round(performance.now() - startedAt);
    return metrics;
  } finally {
    page.off("request", onRequest);
    page.off("response", onResponse);
  }
}

async function recordResponse(metrics, response) {
  const request = response.request();
  const headers = response.headers();
  const path = safePath(response.url());
  metrics.response_count += 1;
  if (response.status() === 304) metrics.not_modified_count += 1;
  if (response.fromServiceWorker()) metrics.service_worker_response_count += 1;
  if (path.startsWith("/api/")) metrics.api_response_count += 1;
  if (String(headers["cache-control"] || "").includes("immutable")) metrics.immutable_response_count += 1;
  try {
    const sizes = await request.sizes();
    metrics.transfer_bytes += Math.max(0, sizes.responseBodySize) + Math.max(0, sizes.responseHeadersSize);
  } catch {
    const length = Number(headers["content-length"] || 0);
    if (Number.isFinite(length) && length > 0) metrics.transfer_bytes += length;
  }
}

async function measureFileRevalidation(context) {
  const first = await context.request.get(fileUrl.href, { failOnStatusCode: false });
  const etag = first.headers().etag || "";
  const firstBody = await first.body();
  const second = await context.request.get(fileUrl.href, {
    failOnStatusCode: false,
    headers: etag ? { "If-None-Match": etag } : {},
  });
  const secondBody = await second.body();
  return {
    first_status: first.status(),
    first_body_bytes: firstBody.byteLength,
    etag_present: Boolean(etag),
    revalidation_status: second.status(),
    revalidation_body_bytes: secondBody.byteLength,
  };
}

async function measureNetworkUnavailableReopen(context, page) {
  await context.setOffline(true);
  const startedAt = performance.now();
  try {
    await page.reload({ waitUntil: "domcontentloaded", timeout: 15_000 });
    await page.locator(".bs-shell").waitFor({ state: "visible", timeout: 5_000 });
    return {
      shell_visible: true,
      elapsed_ms: Math.round(performance.now() - startedAt),
      standard_shell_count: await page.locator(".bs-shell").count(),
      loading_indicator_count: await page.locator('[aria-label="Loading workspace"]').count(),
      legacy_mode_marker_count: await page.locator('.bs-offline-indicator, .bs-offline-workspace-shell, [data-maverick-connectivity]').count(),
      iframe_count: await page.locator("iframe").count(),
    };
  } catch (error) {
    return {
      shell_visible: false,
      elapsed_ms: Math.round(performance.now() - startedAt),
      error: safeError(error),
    };
  } finally {
    await context.setOffline(false);
  }
}

function emptyNavigationMetrics(phase) {
  return {
    phase,
    shell_visible_ms: null,
    total_ms: null,
    request_count: 0,
    response_count: 0,
    api_response_count: 0,
    external_request_count: 0,
    immutable_response_count: 0,
    not_modified_count: 0,
    service_worker_response_count: 0,
    transfer_bytes: 0,
  };
}

function summarize(samples) {
  const cold = samples.map((sample) => sample.cold);
  const warm = samples.flatMap((sample) => sample.warm);
  const numeric = ["shell_visible_ms", "total_ms", "request_count", "transfer_bytes", "service_worker_response_count"];
  return Object.fromEntries(
    [["cold", cold], ["warm", warm]].map(([phase, values]) => [
      phase,
      Object.fromEntries(numeric.map((key) => [key, percentiles(values.map((item) => item[key]).filter(Number.isFinite))])),
    ]),
  );
}

function percentiles(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const pick = (value) => sorted[Math.max(0, Math.ceil((value / 100) * sorted.length) - 1)];
  return { min: sorted[0], p50: pick(50), p75: pick(75), p95: pick(95), max: sorted.at(-1) };
}

function optionalSameOriginUrl(value) {
  if (!value) return null;
  const url = new URL(String(value), baseUrl);
  if (url.origin !== new URL(baseUrl).origin) throw new Error("--file-url must be same-origin");
  return url;
}

function sameOrigin(value) {
  try { return new URL(value).origin === new URL(baseUrl).origin; } catch { return false; }
}

function safePath(value) {
  try { return new URL(value).pathname; } catch { return ""; }
}

function safeError(error) {
  return (error instanceof Error ? error.message : String(error)).split("\n")[0].slice(0, 240);
}

function emit(payload) {
  const rendered = `${JSON.stringify(payload, null, 2)}\n`;
  if (args.output) writeFileSync(String(args.output), rendered, { encoding: "utf8", mode: 0o600 });
  process.stdout.write(rendered);
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

function boundedIntegerArg(parsed, key, fallback, min, max) {
  const value = parsed[key] === undefined ? fallback : Number.parseInt(String(parsed[key]), 10);
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`--${key} must be between ${min} and ${max}`);
  return value;
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
