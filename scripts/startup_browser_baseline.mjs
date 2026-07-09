#!/usr/bin/env node
import { existsSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";

const requireFromChat = createRequire(new URL("../apps/chat/package.json", import.meta.url));
const { chromium, devices } = requireFromChat("playwright");

const args = parseArgs(process.argv.slice(2));
const baseUrl = requiredArg(args, "base-url").replace(/\/$/, "");
const username = requiredArg(args, "username");
const password = requiredArg(args, "password");
const jsonOutput = Boolean(args.json);
const runCount = boundedIntegerArg(args, "runs", 1, 1, 50);
const warmReloadCount = boundedIntegerArg(args, "warm-reloads", 1, 0, 20);
const maxComposerReadyP95Ms = optionalNumberArg(args, "max-composer-ready-p95-ms");
const maxRuntimeThreadWebSocketP95 = optionalNumberArg(args, "max-runtime-thread-websocket-p95");

const profiles = [
  ["desktop", devices["Desktop Chrome"]],
  ["mobile", devices["Pixel 5"]],
];

let browser;
try {
  browser = await chromium.launch({
    executablePath: discoverChromiumExecutablePath(),
  });
} catch (error) {
  printSkipped(`playwright browser unavailable: ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);
  process.exit(0);
}

try {
  const results = [];
  for (const [profileName, device] of profiles) {
    results.push(await measureProfile(profileName, device));
  }
  const payload = {
    metric_source: "authenticated browser startup",
    base_url: baseUrl,
    runs: runCount,
    warm_reloads: warmReloadCount,
    profiles: results,
  };
  const thresholdFailures = thresholdFailuresForPayload(payload);
  if (thresholdFailures.length) {
    payload.threshold_failures = thresholdFailures;
  }
  if (jsonOutput) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    printText(payload);
  }
  if (thresholdFailures.length) {
    process.exitCode = 1;
  }
} finally {
  await browser.close();
}

async function measureProfile(profileName, device) {
  const coldSamples = [];
  const warmSamples = [];
  for (let runIndex = 0; runIndex < runCount; runIndex += 1) {
    const context = await browser.newContext(device);
    const page = await context.newPage();
    try {
      await loginContext(context, profileName, runIndex);
      const recorder = attachMetricRecorder(page);
      coldSamples.push(
        await measureNavigation(page, recorder, {
          profileName,
          runIndex,
          phase: "cold",
          navigate: () => page.goto(`${baseUrl}/app/chat?startup_metrics=1`, { waitUntil: "domcontentloaded" }),
        }),
      );
      for (let warmIndex = 0; warmIndex < warmReloadCount; warmIndex += 1) {
        warmSamples.push(
          await measureNavigation(page, recorder, {
            profileName,
            runIndex,
            phase: "warm",
            warmIndex,
            navigate: () => page.reload({ waitUntil: "domcontentloaded" }),
          }),
        );
      }
    } finally {
      await context.close();
    }
  }
  return {
    profile: profileName,
    runs: runCount,
    warm_reloads: warmReloadCount,
    cold: summarizeSamples(coldSamples),
    warm: summarizeSamples(warmSamples),
    samples: {
      cold: coldSamples,
      warm: warmSamples,
    },
  };
}

async function loginContext(context, profileName, runIndex) {
  const loginResponse = await context.request.post(`${baseUrl}/api/auth/login`, {
    data: { username, password },
  });
  if (!loginResponse.ok()) {
    throw new Error(`Login failed for ${profileName} run ${runIndex + 1}: ${loginResponse.status()} ${await loginResponse.text()}`);
  }
}

function attachMetricRecorder(page) {
  const baseHost = new URL(baseUrl).host;
  const recorder = { activeMetrics: null };

  page.on("request", (request) => {
    const metrics = recorder.activeMetrics;
    if (!metrics) {
      return;
    }
    if (request.resourceType() !== "websocket") {
      metrics.http_request_count += 1;
      try {
        if (new URL(request.url()).host !== baseHost) {
          metrics.external_request_count += 1;
        }
      } catch {
        metrics.external_request_count += 1;
      }
    }
  });
  page.on("response", (response) => {
    const metrics = recorder.activeMetrics;
    if (!metrics) {
      return;
    }
    const length = Number(response.headers()["content-length"] || 0);
    if (Number.isFinite(length) && length > 0) {
      metrics.http_transfer_bytes += length;
    }
  });
  page.on("websocket", (ws) => {
    const metrics = recorder.activeMetrics;
    if (!metrics) {
      return;
    }
    metrics.websocket_count += 1;
    if (metrics.first_websocket_open_ms === null) {
      metrics.first_websocket_open_ms = elapsed(metrics.started_at);
    }
    let isRuntimeThreadSocket = false;
    try {
      isRuntimeThreadSocket = new URL(ws.url()).pathname === "/ws/runtime/threads";
    } catch {
      isRuntimeThreadSocket = false;
    }
    if (isRuntimeThreadSocket) {
      metrics.runtime_thread_websocket_count += 1;
    }
    ws.on("framereceived", (event) => {
      if (
        recorder.activeMetrics !== metrics ||
        !isRuntimeThreadSocket ||
        metrics.first_runtime_thread_snapshot_ms !== null ||
        typeof event.payload !== "string"
      ) {
        return;
      }
      try {
        const frame = JSON.parse(event.payload);
        if (frame?.type !== "runtime.thread.snapshot") {
          return;
        }
        metrics.first_runtime_thread_snapshot_ms = elapsed(metrics.started_at);
        metrics.runtime_thread_snapshot_bytes = Buffer.byteLength(event.payload, "utf8");
        metrics.runtime_thread_snapshot_count = Array.isArray(frame.threads) ? frame.threads.length : 0;
      } catch {
        return;
      }
    });
  });
  return recorder;
}

async function measureNavigation(page, recorder, { profileName, runIndex, phase, warmIndex = null, navigate }) {
  const metrics = {
    profile: profileName,
    run: runIndex + 1,
    phase,
    warm_reload: warmIndex === null ? null : warmIndex + 1,
    shell_visible_ms: null,
    chat_iframe_loaded_ms: null,
    composer_ready_ms: null,
    http_request_count: 0,
    external_request_count: 0,
    http_transfer_bytes: 0,
    websocket_count: 0,
    runtime_thread_websocket_count: 0,
    first_websocket_open_ms: null,
    first_runtime_thread_snapshot_ms: null,
    runtime_thread_snapshot_bytes: 0,
    runtime_thread_snapshot_count: 0,
    iframe_count: 0,
    widget_iframe_count: 0,
  };
  metrics.started_at = performance.now();
  recorder.activeMetrics = metrics;
  try {
    await navigate();
    await page.locator(".bs-shell").waitFor({ state: "visible", timeout: 30_000 });
    metrics.shell_visible_ms = elapsed(metrics.started_at);

    const frameElement = page.locator('iframe.bs-workspace-app-frame.is-active[title="Chat viewport"]').first();
    await frameElement.waitFor({ state: "attached", timeout: 30_000 });
    const frameHandle = await frameElement.elementHandle();
    const frame = frameHandle ? await frameHandle.contentFrame() : null;
    if (!frame) {
      throw new Error(`Chat iframe did not attach for ${profileName} ${phase} run ${runIndex + 1}`);
    }
    await frame.locator(".chatapp-root").waitFor({ state: "visible", timeout: 30_000 });
    metrics.chat_iframe_loaded_ms = elapsed(metrics.started_at);
    const textbox = frame.getByRole("textbox");
    await textbox.waitFor({ state: "visible", timeout: 30_000 });
    await frame.waitForFunction(
      () => {
        const node = document.querySelector('[role="textbox"]');
        if (!(node instanceof HTMLElement)) {
          return false;
        }
        if (node.getAttribute("aria-disabled") === "true") {
          return false;
        }
        if (node.hasAttribute("disabled")) {
          return false;
        }
        return node.getAttribute("contenteditable") !== "false";
      },
      null,
      { timeout: 30_000 },
    );
    metrics.composer_ready_ms = elapsed(metrics.started_at);

    await page.waitForTimeout(750);
    metrics.iframe_count = await page.locator("iframe").count();
    metrics.widget_iframe_count = await page.locator('iframe[src*="/api/apps/widgets/"]').count();
  } finally {
    recorder.activeMetrics = null;
  }
  delete metrics.started_at;
  return metrics;
}

function elapsed(startedAt) {
  return Math.round(performance.now() - startedAt);
}

const NUMERIC_METRICS = [
  "shell_visible_ms",
  "chat_iframe_loaded_ms",
  "composer_ready_ms",
  "http_request_count",
  "external_request_count",
  "http_transfer_bytes",
  "websocket_count",
  "runtime_thread_websocket_count",
  "first_websocket_open_ms",
  "first_runtime_thread_snapshot_ms",
  "runtime_thread_snapshot_bytes",
  "runtime_thread_snapshot_count",
  "iframe_count",
  "widget_iframe_count",
];

function summarizeSamples(samples) {
  const summary = { sample_count: samples.length };
  for (const metric of NUMERIC_METRICS) {
    const values = samples.map((sample) => sample[metric]).filter((value) => typeof value === "number" && Number.isFinite(value));
    if (values.length) {
      summary[metric] = percentileSummary(values);
    }
  }
  return summary;
}

function percentileSummary(values) {
  const sorted = [...values].sort((left, right) => left - right);
  return {
    min: sorted[0],
    p50: percentile(sorted, 50),
    p75: percentile(sorted, 75),
    p95: percentile(sorted, 95),
    max: sorted[sorted.length - 1],
  };
}

function percentile(sortedValues, percentileValue) {
  if (!sortedValues.length) {
    return null;
  }
  const rank = Math.ceil((percentileValue / 100) * sortedValues.length) - 1;
  return sortedValues[Math.max(0, Math.min(sortedValues.length - 1, rank))];
}

function boundedIntegerArg(parsed, key, defaultValue, min, max) {
  const raw = parsed[key];
  if (raw === undefined) {
    return defaultValue;
  }
  const value = Number.parseInt(String(raw), 10);
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`--${key} must be an integer between ${min} and ${max}`);
  }
  return value;
}

function optionalNumberArg(parsed, key) {
  const raw = parsed[key];
  if (raw === undefined) {
    return null;
  }
  const value = Number(String(raw));
  if (!Number.isFinite(value)) {
    throw new Error(`--${key} must be a number`);
  }
  return value;
}

function thresholdFailuresForPayload(payload) {
  const failures = [];
  for (const profile of payload.profiles) {
    for (const phase of ["cold", "warm"]) {
      const summary = profile[phase];
      if (!summary || summary.sample_count === 0) {
        continue;
      }
      const composerP95 = summary.composer_ready_ms?.p95;
      if (maxComposerReadyP95Ms !== null && typeof composerP95 === "number" && composerP95 > maxComposerReadyP95Ms) {
        failures.push({
          profile: profile.profile,
          phase,
          metric: "composer_ready_ms.p95",
          actual: composerP95,
          max: maxComposerReadyP95Ms,
        });
      }
      const runtimeThreadWsP95 = summary.runtime_thread_websocket_count?.p95;
      if (
        maxRuntimeThreadWebSocketP95 !== null &&
        typeof runtimeThreadWsP95 === "number" &&
        runtimeThreadWsP95 > maxRuntimeThreadWebSocketP95
      ) {
        failures.push({
          profile: profile.profile,
          phase,
          metric: "runtime_thread_websocket_count.p95",
          actual: runtimeThreadWsP95,
          max: maxRuntimeThreadWebSocketP95,
        });
      }
    }
  }
  return failures;
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      throw new Error(`Unexpected argument: ${token}`);
    }
    const key = token.slice(2);
    if (key === "json") {
      parsed[key] = true;
      continue;
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for --${key}`);
    }
    parsed[key] = value;
    index += 1;
  }
  return parsed;
}

function requiredArg(parsed, key) {
  const value = parsed[key];
  if (!value) {
    throw new Error(`Missing required --${key}`);
  }
  return String(value);
}

function printText(payload) {
  console.log("Maverick authenticated browser startup baseline");
  console.log(`runs=${payload.runs} warm_reloads=${payload.warm_reloads}`);
  for (const profile of payload.profiles) {
    printSummaryLine(profile.profile, "cold", profile.cold);
    printSummaryLine(profile.profile, "warm", profile.warm);
  }
  if (payload.threshold_failures?.length) {
    console.log("Threshold failures:");
    for (const failure of payload.threshold_failures) {
      console.log(`${failure.profile} ${failure.phase} ${failure.metric}: ${failure.actual} > ${failure.max}`);
    }
  }
}

function printSummaryLine(profileName, phase, summary) {
  if (!summary || summary.sample_count === 0) {
    console.log(`${profileName} ${phase}: no samples`);
    return;
  }
  console.log(
    `${profileName} ${phase}: samples=${summary.sample_count} ` +
      `shell=${formatP(summary.shell_visible_ms)} chat_iframe=${formatP(summary.chat_iframe_loaded_ms)} composer=${formatP(summary.composer_ready_ms)} ` +
      `http=${formatP(summary.http_request_count)} ws=${formatP(summary.websocket_count)} runtime_thread_ws=${formatP(summary.runtime_thread_websocket_count)} ` +
      `snapshot=${formatP(summary.first_runtime_thread_snapshot_ms)}/${formatP(summary.runtime_thread_snapshot_bytes)}B/${formatP(
        summary.runtime_thread_snapshot_count,
      )} threads ` +
      `iframes=${formatP(summary.iframe_count)} widgets=${formatP(summary.widget_iframe_count)} external=${formatP(summary.external_request_count)}`,
  );
}

function formatP(summary) {
  if (!summary) {
    return "n/a";
  }
  return `p50=${summary.p50} p75=${summary.p75} p95=${summary.p95}`;
}

function printSkipped(reason) {
  const payload = {
    metric_source: "authenticated browser startup",
    base_url: baseUrl,
    skipped: true,
    reason,
  };
  if (jsonOutput) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    console.log(`Skipped authenticated browser startup baseline: ${reason}`);
  }
}

function discoverChromiumExecutablePath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  }
  const roots = uniqueStrings([
    process.env.PLAYWRIGHT_BROWSERS_PATH,
    join(homedir(), ".cache", "ms-playwright"),
    "/home/ubuntu/.cache/ms-playwright",
  ]);
  const executableRels = ["chrome-headless-shell-linux64/chrome-headless-shell", "chrome-linux64/chrome"];
  for (const root of roots) {
    if (!root || !existsSync(root)) {
      continue;
    }
    const browserDirs = readdirSync(root)
      .filter((entry) => entry.startsWith("chromium"))
      .sort((left, right) => right.localeCompare(left, undefined, { numeric: true }));
    for (const browserDir of browserDirs) {
      for (const executableRel of executableRels) {
        const candidate = join(root, browserDir, executableRel);
        if (existsSync(candidate)) {
          return candidate;
        }
      }
    }
  }
  return undefined;
}

function uniqueStrings(values) {
  return Array.from(new Set(values.filter(Boolean)));
}
