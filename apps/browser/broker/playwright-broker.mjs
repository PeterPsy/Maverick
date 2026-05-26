#!/usr/bin/env node
import http from "node:http";
import { createRequire } from "node:module";
import { lookup } from "node:dns/promises";
import net from "node:net";
import { randomUUID, timingSafeEqual } from "node:crypto";

const require = createRequire(import.meta.url);
const appPackage = require("../package.json");
const pinnedPlaywrightVersion = appPackage.dependencies?.playwright || "unknown";

const brokerHost = process.env.MAVERICK_BROWSER_BROKER_HOST || "127.0.0.1";
const brokerPort = Number.parseInt(process.env.MAVERICK_BROWSER_BROKER_PORT || "9323", 10);
const wsEndpoint = process.env.MAVERICK_BROWSER_PLAYWRIGHT_WS_ENDPOINT || "ws://127.0.0.1:3100/";
const expectedPlaywrightVersion = process.env.MAVERICK_BROWSER_PLAYWRIGHT_VERSION || pinnedPlaywrightVersion;
const connectTimeoutMs = clampInt(process.env.MAVERICK_BROWSER_CONNECT_TIMEOUT_MS, 1000, 60000, 15000);
const actionTimeoutMs = clampInt(process.env.MAVERICK_BROWSER_ACTION_TIMEOUT_MS, 1000, 60000, 30000);
const dnsTimeoutMs = clampInt(process.env.MAVERICK_BROWSER_DNS_TIMEOUT_MS, 1000, 30000, 5000);
const maxLogRecords = clampInt(process.env.MAVERICK_BROWSER_MAX_LOG_RECORDS, 20, 1000, 200);
const brokerToken = process.env.MAVERICK_BROWSER_BROKER_TOKEN || "";
const proxyBindHost = process.env.MAVERICK_BROWSER_PROXY_BIND_HOST || "127.0.0.1";
const proxyPort = Number.parseInt(process.env.MAVERICK_BROWSER_PROXY_PORT || "9324", 10);
const proxyAdvertisedServer = process.env.MAVERICK_BROWSER_PROXY_SERVER || `http://127.0.0.1:${proxyPort}`;
const restrictedHosts = new Set([
  "docker.for.mac.localhost",
  "docker.for.win.localhost",
  "gateway.docker.internal",
  "host.docker.internal",
  "hostmachine",
  "ip6-localhost",
  "ip6-loopback",
  "localhost",
  "kubernetes.docker.internal",
]);
const metadataHosts = new Set(["metadata", "metadata.google.internal"]);

if (process.argv.includes("--self-test-policy")) {
  await runPolicySelfTest();
  process.exit(0);
}

if (!brokerToken) {
  process.stderr.write("MAVERICK_BROWSER_BROKER_TOKEN is required for the Browser broker.\n");
  process.exit(1);
}

let browserPromise = null;
let browser = null;
let chromiumClient = null;
let playwrightVersion = pinnedPlaywrightVersion;
const sessions = new Map();
const proxyPolicies = new Map();

const server = http.createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
    if (request.method === "GET" && requestUrl.pathname === "/health") {
      authorize(request);
      return sendJson(response, 200, healthPayload());
    }
    if (request.method === "POST" && requestUrl.pathname === "/actions") {
      authorize(request);
      const body = await readJsonBody(request);
      const result = await handleAction(body.action, body.payload || {});
      return sendJson(response, result.statusCode, result.payload);
    }
    sendJson(response, 404, { error: "not_found", detail: "Unknown Browser broker route." });
  } catch (error) {
    sendJson(response, error.statusCode || 500, {
      error: error.code || "broker_error",
      detail: error.message || "Browser broker action failed.",
      policy: error.decision || undefined,
    });
  }
});

const proxyServer = http.createServer((request, response) => {
  void handleProxyHttpRequest(request, response).catch((error) => sendProxyHttpError(response, error));
});

proxyServer.on("connect", (request, socket, head) => {
  void handleProxyConnect(request, socket, head).catch((error) => sendProxyConnectError(socket, error));
});

server.listen(brokerPort, brokerHost, () => {
  process.stdout.write(
    JSON.stringify({
      status: "listening",
      provider: "playwright_lab",
      broker_url: `http://${brokerHost}:${brokerPort}`,
      proxy_server: proxyAdvertisedServer,
      ws_endpoint: redactUrl(wsEndpoint),
      playwright_version: playwrightVersion,
    }) + "\n",
  );
});

proxyServer.listen(proxyPort, proxyBindHost);

process.on("SIGINT", () => void shutdown(0));
process.on("SIGTERM", () => void shutdown(0));

async function handleAction(action, payload) {
  switch (action) {
    case "session.create":
      return { statusCode: 201, payload: await createSession(payload) };
    case "session.close":
      return { statusCode: 200, payload: await closeSession(payload) };
    case "navigate":
      return { statusCode: 200, payload: await navigate(payload) };
    case "snapshot":
      return { statusCode: 200, payload: await snapshot(payload) };
    case "screenshot":
      return { statusCode: 200, payload: await screenshot(payload) };
    case "console.messages":
      return { statusCode: 200, payload: consoleMessages(payload) };
    case "network.requests":
      return { statusCode: 200, payload: networkRequests(payload) };
    case "tabs":
      return { statusCode: 200, payload: tabsPayload(payload) };
    case "wait_for":
      return { statusCode: 200, payload: await waitFor(payload) };
    case "click":
      return { statusCode: 200, payload: await click(payload) };
    case "type":
      return { statusCode: 200, payload: await typeText(payload) };
    case "press_key":
      return { statusCode: 200, payload: await pressKey(payload) };
    default:
      throw brokerError(400, "unsupported_action", `Unsupported Browser broker action: ${action || "<empty>"}.`);
  }
}

async function createSession(payload) {
  assertNoPersistenceOptions(payload);
  const connectedBrowser = await getBrowser();
  const policyContext = policyContextFromPayload(payload);
  if (policyContext.allow_admin_dev_targets && !callerCanAccessAdminDevTargets(payload)) {
    throw brokerError(403, "session_forbidden", "Admin dev Browser sessions require admin authority.");
  }
  const proxyPassword = randomUUID();
  proxyPolicies.set(proxyPassword, policyContext);
  let context;
  try {
    context = await connectedBrowser.newContext({
      acceptDownloads: false,
      bypassCSP: false,
      ignoreHTTPSErrors: false,
      javaScriptEnabled: true,
      permissions: [],
      proxy: {
        server: proxyAdvertisedServer,
        username: "maverick",
        password: proxyPassword,
      },
      serviceWorkers: "block",
      viewport: {
        width: clampInt(payload.viewport_width, 320, 3840, 1440),
        height: clampInt(payload.viewport_height, 320, 2160, 900),
      },
    });
  } catch (error) {
    proxyPolicies.delete(proxyPassword);
    throw error;
  }
  context.setDefaultTimeout(actionTimeoutMs);
  const session = {
    id: randomUUID(),
    context,
    pages: new Set(),
    activePage: null,
    mode: payload.mode === "maverick_dev_inspector" ? "maverick_dev_inspector" : "read_only",
    policyContext,
    proxyPassword,
    lastPolicyBlock: null,
    console: [],
    network: [],
    createdAt: new Date().toISOString(),
  };
  await context.route("**/*", (route) => enforceRoutePolicy(session, route));
  const page = await context.newPage();
  session.pages.add(page);
  session.activePage = page;
  attachPageListeners(session, page);
  sessions.set(session.id, session);
  return {
    session_id: session.id,
    mode: session.mode,
    provider: "playwright_lab",
    isolated: true,
    persistent_profile: false,
    login_state_persisted: false,
    accept_downloads: false,
    file_upload: false,
  };
}

async function closeSession(payload) {
  const session = requireSession(payload);
  assertSessionAccessAllowed(session, payload);
  sessions.delete(session.id);
  proxyPolicies.delete(session.proxyPassword);
  await session.context.close().catch(() => undefined);
  return { session_id: session.id, closed: true };
}

async function navigate(payload) {
  const session = requireSession(payload);
  assertSessionAccessAllowed(session, payload);
  const url = requireString(payload, "url");
  session.lastPolicyBlock = null;
  const decision = await evaluateBrokerEgressUrl(url, session.policyContext);
  if (!decision.allowed) {
    throw policyBrokerError(decision);
  }
  const waitUntil = allowedWaitUntil(payload.wait_until || payload.waitUntil || "domcontentloaded");
  let response;
  try {
    response = await session.activePage.goto(url, { waitUntil, timeout: timeoutFromPayload(payload) });
  } catch (error) {
    if (session.lastPolicyBlock) {
      throw policyBrokerError(session.lastPolicyBlock);
    }
    throw error;
  }
  return {
    session_id: session.id,
    url: redactUrl(session.activePage.url()),
    status: response?.status() || null,
    title: await session.activePage.title().catch(() => ""),
  };
}

async function snapshot(payload) {
  const session = requireSession(payload);
  assertSessionAccessAllowed(session, payload);
  const snapshotText = await session.activePage
    .locator("body")
    .ariaSnapshot({ mode: "ai", timeout: timeoutFromPayload(payload) });
  return {
    session_id: session.id,
    url: redactUrl(session.activePage.url()),
    format: "aria-ai",
    snapshot: snapshotText,
  };
}

async function screenshot(payload) {
  const session = requireSession(payload);
  assertSessionAccessAllowed(session, payload);
  const buffer = await session.activePage.screenshot({
    fullPage: Boolean(payload.full_page || payload.fullPage),
    timeout: timeoutFromPayload(payload),
    type: payload.type === "jpeg" ? "jpeg" : "png",
  });
  return {
    session_id: session.id,
    url: redactUrl(session.activePage.url()),
    mime_type: payload.type === "jpeg" ? "image/jpeg" : "image/png",
    encoding: "base64",
    data: buffer.toString("base64"),
    persisted: false,
  };
}

function consoleMessages(payload) {
  const session = requireSession(payload);
  assertSessionAccessAllowed(session, payload);
  return { session_id: session.id, messages: tail(session.console, payload.limit) };
}

function networkRequests(payload) {
  const session = requireSession(payload);
  assertSessionAccessAllowed(session, payload);
  return { session_id: session.id, requests: tail(session.network, payload.limit) };
}

function tabsPayload(payload) {
  const allowAdminDevTargets = callerCanAccessAdminDevTargets(payload);
  return {
    sessions: [...sessions.values()]
      .filter((session) => !session.policyContext.allow_admin_dev_targets || allowAdminDevTargets)
      .map((session) => ({
        session_id: session.id,
        mode: session.mode,
        tabs: [...session.pages].map((page) => ({
          url: redactUrl(page.url()),
          active: page === session.activePage,
        })),
      })),
  };
}

async function waitFor(payload) {
  const session = requireSession(payload);
  assertSessionAccessAllowed(session, payload);
  if (payload.selector) {
    await session.activePage.locator(String(payload.selector)).first().waitFor({ timeout: timeoutFromPayload(payload) });
  } else {
    await session.activePage.waitForLoadState(allowedWaitUntil(payload.state || "domcontentloaded"), {
      timeout: timeoutFromPayload(payload),
    });
  }
  return { session_id: session.id, url: redactUrl(session.activePage.url()), waited: true };
}

async function click(payload) {
  const session = requireSession(payload);
  await assertDevInspectorActionAllowed(session, payload);
  const selector = requireSelector(payload);
  await session.activePage.locator(selector).first().click({ timeout: timeoutFromPayload(payload) });
  return { session_id: session.id, clicked: true, selector };
}

async function typeText(payload) {
  const session = requireSession(payload);
  await assertDevInspectorActionAllowed(session, payload);
  const selector = requireSelector(payload);
  const text = requireString(payload, "text");
  await session.activePage.locator(selector).first().fill(text, { timeout: timeoutFromPayload(payload) });
  return { session_id: session.id, typed: true, selector };
}

async function pressKey(payload) {
  const session = requireSession(payload);
  await assertDevInspectorActionAllowed(session, payload);
  const key = requireString(payload, "key");
  await session.activePage.keyboard.press(key, { timeout: timeoutFromPayload(payload) });
  return { session_id: session.id, pressed: true, key };
}

async function enforceRoutePolicy(session, route) {
  const request = route.request();
  const decision = await evaluateBrokerEgressUrl(request.url(), session.policyContext);
  if (!decision.allowed) {
    session.lastPolicyBlock = decision;
    pushBounded(session.network, {
      timestamp: new Date().toISOString(),
      event: "policy_blocked",
      method: request.method(),
      url: redactUrl(request.url()),
      resource_type: request.resourceType(),
      reason: decision.reason,
      blocked_address: decision.blocked_address || null,
    });
    await route.abort("blockedbyclient").catch(() => undefined);
    return;
  }
  await route.continue();
}

async function assertResponseServerAddress(session, response) {
  const serverAddr = await response.serverAddr().catch(() => null);
  const ipAddress = serverAddr?.ipAddress;
  if (!ipAddress) {
    return;
  }
  if (isBrokerProxyServerAddress(serverAddr)) {
    return;
  }
  const decision = await evaluateBrokerEgressUrl(response.url(), session.policyContext);
  if (decision.allowed && decision.reason === "allowed_admin_dev_target") {
    return;
  }
  const blockedAddress = restrictedAddress(ipAddress);
  if (!blockedAddress) {
    return;
  }
  const blockedDecision = {
    allowed: false,
    reason: "blocked_restricted_ip",
    url: response.url(),
    redacted_url: redactUrl(response.url()),
    blocked_address: blockedAddress,
  };
  session.lastPolicyBlock = blockedDecision;
  pushBounded(session.network, {
    timestamp: new Date().toISOString(),
    event: "policy_blocked_response",
    status: response.status(),
    url: redactUrl(response.url()),
    reason: blockedDecision.reason,
    blocked_address: blockedAddress,
  });
  await response.frame().page().close().catch(() => undefined);
}

function isBrokerProxyServerAddress(serverAddr) {
  const port = Number.parseInt(String(serverAddr?.port || ""), 10);
  return port === proxyPort;
}

async function evaluateBrokerEgressUrl(rawUrl, policyContext = {}) {
  let url;
  try {
    url = new URL(String(rawUrl).trim());
  } catch {
    return policyDecision(false, "blocked_missing_host", rawUrl);
  }
  const scheme = url.protocol.replace(":", "").toLowerCase();
  if (!["http", "https"].includes(scheme)) {
    return policyDecision(false, "blocked_disallowed_scheme", rawUrl, { scheme });
  }
  const host = normalizeHost(url.hostname);
  if (!host) {
    return policyDecision(false, "blocked_missing_host", rawUrl, { scheme });
  }
  const port = Number.parseInt(url.port || defaultPort(scheme), 10);
  if (isAdminDevTarget(scheme, host, port)) {
    if (policyContext.allow_admin_dev_targets === true) {
      return policyDecision(true, "allowed_admin_dev_target", rawUrl, { scheme, host, port });
    }
    return policyDecision(false, "blocked_admin_dev_target_not_enabled", rawUrl, { scheme, host, port });
  }
  if (metadataHosts.has(host)) {
    return policyDecision(false, "blocked_metadata_host", rawUrl, { scheme, host, port });
  }
  if (restrictedHosts.has(host) || host.endsWith(".localhost")) {
    return policyDecision(false, "blocked_restricted_host", rawUrl, {
      scheme,
      host,
      port,
      blocked_address: host,
    });
  }
  const hostAddress = parseIpAddress(host);
  if (hostAddress) {
    const blockedAddress = restrictedAddress(hostAddress);
    return policyDecision(!blockedAddress, blockedAddress ? "blocked_restricted_ip" : "allowed_public_http", rawUrl, {
      scheme,
      host,
      port,
      blocked_address: blockedAddress,
    });
  }
  const resolved = await resolveHostAddresses(host);
  if (resolved.length === 0) {
    return policyDecision(false, "blocked_no_resolved_addresses", rawUrl, { scheme, host, port });
  }
  for (const address of resolved) {
    const blockedAddress = restrictedAddress(address);
    if (blockedAddress) {
      return policyDecision(false, "blocked_restricted_ip", rawUrl, {
        scheme,
        host,
        port,
        blocked_address: blockedAddress,
      });
    }
  }
  return policyDecision(true, "allowed_public_http", rawUrl, { scheme, host, port });
}

async function getBrowser() {
  const chromium = await loadPlaywrightClient();
  if (playwrightVersion !== expectedPlaywrightVersion) {
    throw brokerError(
      503,
      "playwright_version_mismatch",
      `Playwright client version ${playwrightVersion} does not match expected ${expectedPlaywrightVersion}.`,
    );
  }
  if (browser?.isConnected()) {
    return browser;
  }
  if (!browserPromise) {
    browserPromise = chromium.connect(wsEndpoint, { timeout: connectTimeoutMs }).then((connected) => {
      browser = connected;
      browser.on("disconnected", () => {
      browser = null;
      browserPromise = null;
      sessions.clear();
      proxyPolicies.clear();
    });
      return browser;
    });
  }
  try {
    return await browserPromise;
  } catch (error) {
    browserPromise = null;
    throw brokerError(503, "playwright_server_unavailable", `Cannot connect to Playwright run-server at ${redactUrl(wsEndpoint)}.`);
  }
}

async function loadPlaywrightClient() {
  if (chromiumClient) {
    return chromiumClient;
  }
  try {
    const playwright = await import("playwright");
    const packageJson = require("playwright/package.json");
    playwrightVersion = packageJson.version;
    chromiumClient = playwright.chromium;
    return chromiumClient;
  } catch (error) {
    throw brokerError(503, "playwright_client_unavailable", "Run npm ci in apps/browser before starting the broker.");
  }
}

function attachPageListeners(session, page) {
  page.on("console", (message) => {
    pushBounded(session.console, {
      timestamp: new Date().toISOString(),
      type: message.type(),
      text: message.text().slice(0, 4000),
      location: message.location(),
    });
  });
  page.on("request", (request) => {
    pushBounded(session.network, {
      timestamp: new Date().toISOString(),
      event: "request",
      method: request.method(),
      url: redactUrl(request.url()),
      resource_type: request.resourceType(),
    });
  });
  page.on("response", (response) => {
    pushBounded(session.network, {
      timestamp: new Date().toISOString(),
      event: "response",
      status: response.status(),
      url: redactUrl(response.url()),
    });
    void assertResponseServerAddress(session, response);
  });
  page.on("requestfailed", (request) => {
    pushBounded(session.network, {
      timestamp: new Date().toISOString(),
      event: "requestfailed",
      method: request.method(),
      url: redactUrl(request.url()),
      failure: request.failure()?.errorText || "unknown",
    });
  });
  page.on("download", async (download) => {
    pushBounded(session.console, {
      timestamp: new Date().toISOString(),
      type: "warning",
      text: `download blocked: ${download.suggestedFilename()}`,
    });
    await download.cancel().catch(() => undefined);
  });
  page.on("filechooser", () => {
    pushBounded(session.console, {
      timestamp: new Date().toISOString(),
      type: "warning",
      text: "file upload blocked by Browser P0 policy",
    });
  });
  page.on("dialog", (dialog) => void dialog.dismiss().catch(() => undefined));
}

function policyContextFromPayload(payload) {
  const context = payload?.policy_context;
  return {
    allow_admin_dev_targets: Boolean(
      context && typeof context === "object" && context.allow_admin_dev_targets === true,
    ),
  };
}

function policyDecision(allowed, reason, rawUrl, details = {}) {
  return {
    allowed,
    reason,
    url: String(rawUrl),
    redacted_url: redactUrl(String(rawUrl)),
    ...details,
  };
}

function policyBrokerError(decision) {
  const error = brokerError(403, "policy_denied", `Browser broker egress policy denied ${decision.redacted_url}.`);
  error.decision = decision;
  return error;
}

function callerCanAccessAdminDevTargets(payload) {
  const context = payload?.caller_context;
  return Boolean(context && typeof context === "object" && context.admin_dev_targets_enabled === true);
}

function assertSessionAccessAllowed(session, payload) {
  if (session.policyContext.allow_admin_dev_targets && !callerCanAccessAdminDevTargets(payload)) {
    throw brokerError(403, "session_forbidden", "Admin dev Browser session access requires admin authority.");
  }
}

async function assertDevInspectorActionAllowed(session, payload) {
  assertSessionAccessAllowed(session, payload);
  if (session.mode !== "maverick_dev_inspector") {
    throw brokerError(403, "interactive_action_forbidden", "Interactive actions require maverick_dev_inspector mode.");
  }
  const targetUrl = requireString(payload, "target_url");
  const targetDecision = await evaluateBrokerEgressUrl(targetUrl, session.policyContext);
  if (!targetDecision.allowed || targetDecision.reason !== "allowed_admin_dev_target") {
    throw policyBrokerError(targetDecision);
  }
  const activeUrl = session.activePage?.url?.() || "";
  const activeDecision = await evaluateBrokerEgressUrl(activeUrl, session.policyContext);
  if (!activeDecision.allowed || activeDecision.reason !== "allowed_admin_dev_target") {
    throw policyBrokerError(activeDecision);
  }
}

async function resolveHostAddresses(host) {
  try {
    const records = await Promise.race([
      lookup(host, { all: true, verbatim: true }),
      new Promise((_, reject) => setTimeout(() => reject(new Error("dns_timeout")), dnsTimeoutMs)),
    ]);
    return [...new Set(records.map((record) => record.address).filter(Boolean))].sort();
  } catch {
    return [];
  }
}

function normalizeHost(host) {
  return String(host || "")
    .trim()
    .toLowerCase()
    .replace(/^\[(.*)\]$/, "$1")
    .replace(/\.$/, "");
}

function defaultPort(scheme) {
  return scheme === "https" ? "443" : "80";
}

function isAdminDevTarget(scheme, host, port) {
  return scheme === "http" && host === "hostmachine" && port === 8000;
}

function parseIpAddress(value) {
  const normalized = normalizeHost(value);
  const version = net.isIP(normalized);
  if (version === 4) {
    return normalized;
  }
  if (version === 6) {
    return normalized;
  }
  return null;
}

function restrictedAddress(address) {
  const normalized = parseIpAddress(address);
  if (!normalized) {
    return String(address);
  }
  if (net.isIP(normalized) === 4) {
    return restrictedIpv4(normalized) ? normalized : null;
  }
  return restrictedIpv6(normalized) ? normalized : null;
}

function restrictedIpv4(address) {
  const value = ipv4ToInt(address);
  if (value === null) {
    return true;
  }
  const ranges = [
    ["0.0.0.0", 8],
    ["10.0.0.0", 8],
    ["100.64.0.0", 10],
    ["100.100.100.200", 32],
    ["127.0.0.0", 8],
    ["169.254.0.0", 16],
    ["172.16.0.0", 12],
    ["192.0.0.0", 24],
    ["192.0.2.0", 24],
    ["192.168.0.0", 16],
    ["198.18.0.0", 15],
    ["198.51.100.0", 24],
    ["203.0.113.0", 24],
    ["224.0.0.0", 4],
    ["240.0.0.0", 4],
  ];
  return ranges.some(([network, prefix]) => ipv4InRange(value, ipv4ToInt(network), prefix));
}

function restrictedIpv6(address) {
  const value = ipv6ToBigInt(address);
  if (value === null) {
    return true;
  }
  const embedded = embeddedRestrictedIpv4(value);
  if (embedded) {
    return true;
  }
  const ranges = [
    ["::", 128],
    ["::1", 128],
    ["64:ff9b:1::", 48],
    ["100::", 64],
    ["2001::", 32],
    ["2001:2::", 48],
    ["2001:10::", 28],
    ["2001:db8::", 32],
    ["fc00::", 7],
    ["fd00:ec2::254", 128],
    ["fe80::", 10],
    ["ff00::", 8],
  ];
  return ranges.some(([network, prefix]) => ipv6InRange(value, ipv6ToBigInt(network), prefix));
}

function embeddedRestrictedIpv4(value) {
  const mappedPrefix = value >> 32n;
  if (mappedPrefix === 0xffffn && restrictedIpv4(intToIpv4(Number(value & 0xffffffffn)))) {
    return true;
  }
  if (ipv6InRange(value, ipv6ToBigInt("2002::"), 16)) {
    const embedded = Number((value >> 80n) & 0xffffffffn);
    return restrictedIpv4(intToIpv4(embedded));
  }
  if (ipv6InRange(value, ipv6ToBigInt("64:ff9b::"), 96)) {
    return restrictedIpv4(intToIpv4(Number(value & 0xffffffffn)));
  }
  return false;
}

function ipv4ToInt(address) {
  const parts = String(address).split(".");
  if (parts.length !== 4) {
    return null;
  }
  let value = 0;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) {
      return null;
    }
    const octet = Number.parseInt(part, 10);
    if (octet < 0 || octet > 255) {
      return null;
    }
    value = (value << 8) + octet;
  }
  return value >>> 0;
}

function intToIpv4(value) {
  return [24, 16, 8, 0].map((shift) => (value >>> shift) & 255).join(".");
}

function ipv4InRange(value, network, prefix) {
  if (network === null) {
    return false;
  }
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
  return (value & mask) === (network & mask);
}

function ipv6ToBigInt(address) {
  let value = normalizeHost(address);
  if (!value || value.includes("%")) {
    return null;
  }
  if (value.includes(".")) {
    const lastColon = value.lastIndexOf(":");
    const ipv4 = ipv4ToInt(value.slice(lastColon + 1));
    if (lastColon < 0 || ipv4 === null) {
      return null;
    }
    value = `${value.slice(0, lastColon)}:${((ipv4 >>> 16) & 0xffff).toString(16)}:${(ipv4 & 0xffff).toString(16)}`;
  }
  const halves = value.split("::");
  if (halves.length > 2) {
    return null;
  }
  const left = halves[0] ? halves[0].split(":") : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const fill = halves.length === 2 ? 8 - left.length - right.length : 0;
  const parts = halves.length === 2 ? [...left, ...Array(fill).fill("0"), ...right] : left;
  if (fill < 0 || parts.length !== 8) {
    return null;
  }
  let result = 0n;
  for (const part of parts) {
    if (!/^[0-9a-f]{1,4}$/i.test(part)) {
      return null;
    }
    result = (result << 16n) + BigInt(Number.parseInt(part, 16));
  }
  return result;
}

function ipv6InRange(value, network, prefix) {
  if (value === null || network === null) {
    return false;
  }
  const hostBits = BigInt(128 - prefix);
  const mask = hostBits === 0n ? (1n << 128n) - 1n : ((1n << 128n) - 1n) ^ ((1n << hostBits) - 1n);
  return (value & mask) === (network & mask);
}

function requireSession(payload) {
  const sessionId = requireString(payload, "session_id");
  const session = sessions.get(sessionId);
  if (!session) {
    throw brokerError(404, "unknown_session", `Unknown Browser session: ${sessionId}.`);
  }
  return session;
}

function requireString(payload, field) {
  const value = payload?.[field];
  if (typeof value !== "string" || value.trim() === "") {
    throw brokerError(400, "validation_error", `${field} is required.`);
  }
  return value.trim();
}

function requireSelector(payload) {
  const selector = payload.selector || payload.ref;
  if (typeof selector !== "string" || selector.trim() === "") {
    throw brokerError(400, "validation_error", "selector or ref is required.");
  }
  return selector.trim();
}

function assertNoPersistenceOptions(payload) {
  const forbidden = [
    "acceptDownloads",
    "accept_downloads",
    "downloadsPath",
    "downloads_path",
    "storageState",
    "storage_state",
    "userDataDir",
    "user_data_dir",
    "profile",
    "profileId",
    "profile_id",
  ];
  const found = forbidden.find((field) => Object.prototype.hasOwnProperty.call(payload, field));
  if (found) {
    throw brokerError(400, "p0_persistence_disabled", `P0 Browser sessions do not accept ${found}.`);
  }
}

function allowedWaitUntil(value) {
  const normalized = String(value || "").trim();
  if (["load", "domcontentloaded", "networkidle"].includes(normalized)) {
    return normalized;
  }
  throw brokerError(400, "validation_error", "wait state must be load, domcontentloaded, or networkidle.");
}

function timeoutFromPayload(payload) {
  return clampInt(payload.timeout_ms ?? payload.timeoutMs, 0, 30000, actionTimeoutMs);
}

function tail(records, limit) {
  const count = clampInt(limit, 1, maxLogRecords, 100);
  return records.slice(-count);
}

function pushBounded(records, record) {
  records.push(record);
  if (records.length > maxLogRecords) {
    records.splice(0, records.length - maxLogRecords);
  }
}

async function handleProxyHttpRequest(request, response) {
  const policyContext = proxyPolicyContext(request);
  const requestUrl = new URL(request.url);
  const target = await resolveAllowedConnection(requestUrl, policyContext);
  const headers = proxyForwardHeaders(request.headers, requestUrl.host);
  const upstream = http.request(
    {
      host: target.address,
      port: target.port,
      method: request.method,
      path: `${requestUrl.pathname}${requestUrl.search}`,
      headers,
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );
  upstream.on("error", (error) => sendProxyHttpError(response, brokerError(502, "proxy_upstream_error", error.message)));
  request.pipe(upstream);
}

async function handleProxyConnect(request, socket, head) {
  const policyContext = proxyPolicyContext(request);
  const requestUrl = new URL(`https://${request.url}`);
  const target = await resolveAllowedConnection(requestUrl, policyContext);
  const upstream = net.connect({ host: target.address, port: target.port }, () => {
    socket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
    if (head?.length) {
      upstream.write(head);
    }
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
}

function proxyPolicyContext(request) {
  const auth = request.headers["proxy-authorization"] || "";
  const prefix = "Basic ";
  if (!auth.startsWith(prefix)) {
    throw brokerError(407, "proxy_auth_required", "Browser broker proxy credentials are required.");
  }
  const decoded = Buffer.from(auth.slice(prefix.length), "base64").toString("utf8");
  const separator = decoded.indexOf(":");
  const username = separator >= 0 ? decoded.slice(0, separator) : "";
  const password = separator >= 0 ? decoded.slice(separator + 1) : "";
  if (username !== "maverick" || !proxyPolicies.has(password)) {
    throw brokerError(407, "proxy_auth_required", "Browser broker proxy credentials are invalid.");
  }
  return proxyPolicies.get(password);
}

async function resolveAllowedConnection(requestUrl, policyContext) {
  const decision = await evaluateBrokerEgressUrl(requestUrl.toString(), policyContext);
  if (!decision.allowed) {
    throw policyBrokerError(decision);
  }
  const scheme = requestUrl.protocol.replace(":", "").toLowerCase();
  const host = normalizeHost(requestUrl.hostname);
  const port = Number.parseInt(requestUrl.port || defaultPort(scheme), 10);
  if (isAdminDevTarget(scheme, host, port) && policyContext.allow_admin_dev_targets === true) {
    return { address: "127.0.0.1", host, port };
  }
  const hostAddress = parseIpAddress(host);
  if (hostAddress) {
    return { address: hostAddress, host, port };
  }
  const addresses = await resolveHostAddresses(host);
  for (const address of addresses) {
    if (!restrictedAddress(address)) {
      return { address, host, port };
    }
  }
  throw policyBrokerError(
    policyDecision(false, "blocked_no_resolved_addresses", requestUrl.toString(), { scheme, host, port }),
  );
}

function proxyForwardHeaders(headers, host) {
  const forwarded = { ...headers, host };
  delete forwarded["proxy-authorization"];
  delete forwarded["proxy-connection"];
  delete forwarded.connection;
  return forwarded;
}

function sendProxyHttpError(response, error) {
  if (response.headersSent) {
    response.destroy();
    return;
  }
  const status = error.statusCode === 407 ? 407 : error.statusCode || 502;
  if (status === 407) {
    response.setHeader("Proxy-Authenticate", 'Basic realm="maverick-browser"');
  }
  sendJson(response, status, {
    error: error.code || "proxy_error",
    detail: error.message || "Browser broker proxy request failed.",
    policy: error.decision || undefined,
  });
}

function sendProxyConnectError(socket, error) {
  const status = error.statusCode === 407 ? 407 : error.statusCode || 502;
  const headers =
    status === 407 ? 'Proxy-Authenticate: Basic realm="maverick-browser"\r\n' : "Content-Type: text/plain\r\n";
  socket.write(`HTTP/1.1 ${status} Proxy Error\r\n${headers}\r\n`);
  socket.destroy();
}

function healthPayload() {
  return {
    status: "ready",
    provider: "playwright_lab",
    playwright_version: playwrightVersion,
    expected_playwright_version: expectedPlaywrightVersion,
    ws_endpoint: redactUrl(wsEndpoint),
    proxy_server: proxyAdvertisedServer,
    connected: Boolean(browser?.isConnected()),
    session_count: sessions.size,
    constraints: {
      isolated_sessions: true,
      persistent_profiles: false,
      login_state_persistence: false,
      file_upload: false,
      automatic_download_persistence: false,
    },
  };
}

function authorize(request) {
  const expected = `Bearer ${brokerToken}`;
  const received = request.headers.authorization || "";
  if (!secureEqual(received, expected)) {
    throw brokerError(401, "unauthorized", "Browser broker token is missing or invalid.");
  }
}

function secureEqual(left, right) {
  const leftBuffer = Buffer.from(String(left));
  const rightBuffer = Buffer.from(String(right));
  if (leftBuffer.length !== rightBuffer.length) {
    return false;
  }
  return timingSafeEqual(leftBuffer, rightBuffer);
}

async function readJsonBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  if (chunks.length === 0) {
    return {};
  }
  try {
    const decoded = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) {
      throw new Error("JSON body must be an object.");
    }
    return decoded;
  } catch (error) {
    throw brokerError(400, "invalid_json", "Request body must be valid JSON.");
  }
}

function sendJson(response, statusCode, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  response.end(body);
}

function clampInt(value, min, max, fallback) {
  const number = Number.parseInt(value, 10);
  if (!Number.isFinite(number)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, number));
}

function redactUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    url.username = "";
    url.password = "";
    if (url.search) {
      url.search = "?redacted";
    }
    url.hash = "";
    return url.toString();
  } catch {
    return "<invalid-url>";
  }
}

function brokerError(statusCode, code, message) {
  const error = new Error(message);
  error.statusCode = statusCode;
  error.code = code;
  return error;
}

async function runPolicySelfTest() {
  const cases = [
    ["file:///etc/passwd", {}, false, "blocked_disallowed_scheme"],
    ["http://127.0.0.1:8000", {}, false, "blocked_restricted_ip"],
    ["http://0x7f000001/", {}, false, "blocked_restricted_ip"],
    ["http://169.254.169.254/latest/meta-data/", {}, false, "blocked_restricted_ip"],
    ["http://metadata.google.internal/computeMetadata/v1/", {}, false, "blocked_metadata_host"],
    ["http://host.docker.internal/", {}, false, "blocked_restricted_host"],
    ["http://hostmachine:8000/apps/base-shell/", {}, false, "blocked_admin_dev_target_not_enabled"],
    [
      "http://hostmachine:8000/apps/base-shell/",
      { allow_admin_dev_targets: true },
      true,
      "allowed_admin_dev_target",
    ],
    ["https://93.184.216.34/", {}, true, "allowed_public_http"],
    ["http://[::ffff:127.0.0.1]/", {}, false, "blocked_restricted_ip"],
    ["http://[64:ff9b::7f00:1]/", {}, false, "blocked_restricted_ip"],
    ["http://[2001:2::1]/", {}, false, "blocked_restricted_ip"],
    ["http://[2001:10::1]/", {}, false, "blocked_restricted_ip"],
  ];
  for (const [url, context, allowed, reason] of cases) {
    const decision = await evaluateBrokerEgressUrl(url, context);
    if (decision.allowed !== allowed || decision.reason !== reason) {
      throw new Error(
        `Policy self-test failed for ${url}: expected ${allowed}/${reason}, got ${decision.allowed}/${decision.reason}`,
      );
    }
  }
  const adminTarget = await resolveAllowedConnection(new URL("http://hostmachine:8000/apps/base-shell/"), {
    allow_admin_dev_targets: true,
  });
  if (adminTarget.address !== "127.0.0.1") {
    throw new Error(`Policy self-test failed for admin proxy target: ${adminTarget.address}`);
  }
  try {
    await resolveAllowedConnection(new URL("http://127.0.0.1:8000/"), {});
    throw new Error("Policy self-test failed: restricted proxy target was allowed.");
  } catch (error) {
    if (error.code !== "policy_denied") {
      throw error;
    }
  }
  const devSession = {
    mode: "maverick_dev_inspector",
    policyContext: { allow_admin_dev_targets: true },
    activePage: { url: () => "http://hostmachine:8000/apps/base-shell/" },
  };
  const nonAdminDevPayload = {
    policy_context: { allow_admin_dev_targets: true },
    caller_context: { admin_dev_targets_enabled: false },
  };
  const nonAdminDevPolicy = policyContextFromPayload(nonAdminDevPayload);
  if (nonAdminDevPolicy.allow_admin_dev_targets && !callerCanAccessAdminDevTargets(nonAdminDevPayload)) {
    const expectedError = brokerError(403, "session_forbidden", "Admin dev Browser sessions require admin authority.");
    if (expectedError.code !== "session_forbidden") {
      throw expectedError;
    }
  } else {
    throw new Error("Policy self-test failed: non-admin admin-dev session payload accepted.");
  }
  await assertDevInspectorActionAllowed(devSession, {
    target_url: "http://hostmachine:8000/apps/base-shell/",
    caller_context: { admin_dev_targets_enabled: true },
  });
  let adminDevResponseClosed = false;
  await assertResponseServerAddress(devSession, {
    serverAddr: async () => ({ ipAddress: "127.0.0.1", port: 8000 }),
    url: () => "http://hostmachine:8000/apps/base-shell/",
    status: () => 200,
    frame: () => ({
      page: () => ({
        close: async () => {
          adminDevResponseClosed = true;
        },
      }),
    }),
  });
  if (adminDevResponseClosed || devSession.lastPolicyBlock) {
    throw new Error("Policy self-test failed: admin dev response address was blocked.");
  }
  let proxiedResponseClosed = false;
  const proxiedSession = { ...devSession, network: [], lastPolicyBlock: null };
  await assertResponseServerAddress(proxiedSession, {
    serverAddr: async () => ({ ipAddress: "127.0.0.1", port: proxyPort }),
    url: () => "https://fonts.googleapis.com/css2?family=Inter",
    status: () => 200,
    frame: () => ({
      page: () => ({
        close: async () => {
          proxiedResponseClosed = true;
        },
      }),
    }),
  });
  if (proxiedResponseClosed || proxiedSession.lastPolicyBlock) {
    throw new Error("Policy self-test failed: proxied response address was blocked.");
  }
  try {
    await assertDevInspectorActionAllowed(
      { ...devSession, activePage: { url: () => "https://93.184.216.34/" } },
      {
        target_url: "http://hostmachine:8000/apps/base-shell/",
        caller_context: { admin_dev_targets_enabled: true },
      },
    );
    throw new Error("Policy self-test failed: public active page accepted for dev inspector action.");
  } catch (error) {
    if (error.code !== "policy_denied") {
      throw error;
    }
  }
  try {
    assertSessionAccessAllowed(devSession, { caller_context: { admin_dev_targets_enabled: false } });
    throw new Error("Policy self-test failed: non-admin accessed admin dev session.");
  } catch (error) {
    if (error.code !== "session_forbidden") {
      throw error;
    }
  }
  process.stdout.write(JSON.stringify({ status: "ok", cases: cases.length + 8 }) + "\n");
}

async function shutdown(code) {
  server.close();
  proxyServer.close();
  await Promise.all([...sessions.values()].map((session) => session.context.close().catch(() => undefined)));
  sessions.clear();
  proxyPolicies.clear();
  await browser?.close().catch(() => undefined);
  process.exit(code);
}
