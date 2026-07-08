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
    profiles: results,
  };
  if (jsonOutput) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    printText(payload);
  }
} finally {
  await browser.close();
}

async function measureProfile(profileName, device) {
  const context = await browser.newContext(device);
  const page = await context.newPage();
  const baseHost = new URL(baseUrl).host;
  const startedAt = performance.now();
  const metrics = {
    profile: profileName,
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

  page.on("request", (request) => {
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
    const length = Number(response.headers()["content-length"] || 0);
    if (Number.isFinite(length) && length > 0) {
      metrics.http_transfer_bytes += length;
    }
  });
  page.on("websocket", (ws) => {
    metrics.websocket_count += 1;
    if (metrics.first_websocket_open_ms === null) {
      metrics.first_websocket_open_ms = elapsed(startedAt);
    }
    const isRuntimeThreadSocket = new URL(ws.url()).pathname === "/ws/runtime/threads";
    if (isRuntimeThreadSocket) {
      metrics.runtime_thread_websocket_count += 1;
    }
    ws.on("framereceived", (event) => {
      if (!isRuntimeThreadSocket || metrics.first_runtime_thread_snapshot_ms !== null || typeof event.payload !== "string") {
        return;
      }
      try {
        const frame = JSON.parse(event.payload);
        if (frame?.type !== "runtime.thread.snapshot") {
          return;
        }
        metrics.first_runtime_thread_snapshot_ms = elapsed(startedAt);
        metrics.runtime_thread_snapshot_bytes = Buffer.byteLength(event.payload, "utf8");
        metrics.runtime_thread_snapshot_count = Array.isArray(frame.threads) ? frame.threads.length : 0;
      } catch {
        return;
      }
    });
  });

  const loginResponse = await context.request.post(`${baseUrl}/api/auth/login`, {
    data: { username, password },
  });
  if (!loginResponse.ok()) {
    throw new Error(`Login failed for ${profileName}: ${loginResponse.status()} ${await loginResponse.text()}`);
  }

  await page.goto(`${baseUrl}/app/chat?startup_metrics=1`, { waitUntil: "domcontentloaded" });
  await page.locator(".bs-shell").waitFor({ state: "visible", timeout: 30_000 });
  metrics.shell_visible_ms = elapsed(startedAt);

  const frameElement = page.locator('iframe.bs-workspace-app-frame.is-active[title="Chat viewport"]').first();
  await frameElement.waitFor({ state: "attached", timeout: 30_000 });
  const frameHandle = await frameElement.elementHandle();
  const frame = frameHandle ? await frameHandle.contentFrame() : null;
  if (!frame) {
    throw new Error(`Chat iframe did not attach for ${profileName}`);
  }
  await frame.locator(".chatapp-root").waitFor({ state: "visible", timeout: 30_000 });
  metrics.chat_iframe_loaded_ms = elapsed(startedAt);
  const textbox = frame.getByRole("textbox");
  await textbox.waitFor({ state: "visible", timeout: 30_000 });
  await frame.waitForFunction(() => {
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
  });
  metrics.composer_ready_ms = elapsed(startedAt);

  await page.waitForTimeout(750);
  metrics.iframe_count = await page.locator("iframe").count();
  metrics.widget_iframe_count = await page.locator('iframe[src*="/api/apps/widgets/"]').count();
  await context.close();
  return metrics;
}

function elapsed(startedAt) {
  return Math.round(performance.now() - startedAt);
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
  for (const profile of payload.profiles) {
    console.log(
      `${profile.profile}: shell=${profile.shell_visible_ms}ms chat_iframe=${profile.chat_iframe_loaded_ms}ms composer=${profile.composer_ready_ms}ms ` +
        `http=${profile.http_request_count} ws=${profile.websocket_count} runtime_thread_ws=${profile.runtime_thread_websocket_count} ` +
        `snapshot=${profile.first_runtime_thread_snapshot_ms}ms/${profile.runtime_thread_snapshot_bytes}B/${profile.runtime_thread_snapshot_count} threads ` +
        `iframes=${profile.iframe_count} widgets=${profile.widget_iframe_count} external=${profile.external_request_count}`,
    );
  }
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
