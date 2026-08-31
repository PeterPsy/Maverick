#!/usr/bin/env node

import http from "node:http";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { createServer } from "vite";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const HARNESS_ROOT = path.join(APP_ROOT, "tests/native_deep_link_harness");
const DESIGN_STUDIO_ENTRY = path.join(APP_ROOT, "frontend/src/main.tsx");
const expectedPath = "/projects/e2e_project/conversations/e2e_conversation";
const tickets = new Map();
const confirmations = new Map();
const nativePaths = new Set();
const launchPaths = [];

const nativeServer = http.createServer((request, response) => {
  if (request.method === "GET" && nativePaths.has(request.url)) {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(`<!doctype html><main data-native-path="${escapeHtml(request.url)}">native</main>`);
    return;
  }
  if (request.method !== "POST" || request.url !== "/.well-known/maverick-sidecar-bootstrap") {
    response.writeHead(404).end();
    return;
  }
  collectBody(request).then((body) => {
    const ticket = new URLSearchParams(body).get("ticket") || "";
    const launch = tickets.get(ticket);
    tickets.delete(ticket);
    if (!launch) {
      response.writeHead(403).end();
      return;
    }
    confirmations.set(launch.confirmationToken, "ready");
    nativePaths.add(launch.nativePath);
    response.writeHead(303, { Location: launch.nativePath }).end();
  });
});
await listen(nativeServer);
const nativeAddress = nativeServer.address();
if (!nativeAddress || typeof nativeAddress === "string") throw new Error("Native test server did not bind.");
const nativeOrigin = `http://127.0.0.1:${nativeAddress.port}`;

const vite = await createServer({
  root: HARNESS_ROOT,
  plugins: [
    react(),
    {
      name: "native-design-studio-e2e-boundary",
      configureServer(server) {
        server.middlewares.use(async (request, response, next) => {
          if (request.method === "GET" && request.url?.split("?", 1)[0] === "/apps/design-studio/") {
            const html = `<!doctype html><html><body><div id="root"></div><script type="module" src="/@fs/${DESIGN_STUDIO_ENTRY}"></script></body></html>`;
            response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
            response.end(await server.transformIndexHtml(request.url, html));
            return;
          }
          if (request.method === "POST" && request.url === "/api/app-sidecars/browser-launch") {
            const body = JSON.parse(await collectBody(request));
            const nativePath = String(body.path || "");
            const ticket = `e2e_${tickets.size.toString().padStart(8, "0")}`;
            const confirmationToken = `confirmation_${tickets.size.toString().padStart(8, "0")}`;
            launchPaths.push(nativePath);
            tickets.set(ticket, { confirmationToken, nativePath });
            confirmations.set(confirmationToken, "pending");
            response.writeHead(200, { "Content-Type": "application/json" });
            response.end(JSON.stringify({
              origin: nativeOrigin,
              bootstrap_url: `${nativeOrigin}/.well-known/maverick-sidecar-bootstrap`,
              method: "POST",
              ticket_field: "ticket",
              ticket,
              confirmation_token: confirmationToken,
              expires_in_seconds: 30,
              sidecar_instance_id: "native_e2e_instance",
            }));
            return;
          }
          if (request.method === "POST" && request.url === "/api/app-sidecars/browser-launch-status") {
            const body = JSON.parse(await collectBody(request));
            const status = confirmations.get(String(body.confirmation_token || ""));
            response.writeHead(status ? 200 : 410, {
              "Cache-Control": "no-store",
              "Content-Type": "application/json",
            });
            response.end(JSON.stringify(status
              ? { status }
              : { error: "sidecar_bootstrap_confirmation_expired" }));
            return;
          }
          next();
        });
      },
    },
  ],
  server: { host: "127.0.0.1", port: 0 },
  logLevel: "error",
});

let browser;
try {
  await vite.listen();
  const address = vite.httpServer?.address();
  if (!address || typeof address === "string") throw new Error("Shell test server did not bind.");
  useInstalledBrowserCache();
  const { chromium } = await import("playwright");
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto(
    `http://127.0.0.1:${address.port}/app/design-studio${expectedPath}`,
    { waitUntil: "domcontentloaded" },
  );
  await page.waitForFunction(
    ({ origin, expected }) => Array.from(window.frames).length > 0
      && performance.getEntriesByType("resource").some((entry) => entry.name.includes("/apps/design-studio/"))
      && Boolean(origin && expected),
    { origin: nativeOrigin, expected: expectedPath },
  );
  let nativeFrame;
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    nativeFrame = page.frames().find((frame) => frame.url().startsWith(nativeOrigin));
    if (nativeFrame && await nativeFrame.locator("main[data-native-path]").getAttribute("data-native-path") === expectedPath) break;
    await page.waitForTimeout(50);
  }
  if (!nativeFrame) throw new Error("Design Studio did not bootstrap the isolated OpenDesign iframe.");
  const receivedPath = await nativeFrame.locator("main[data-native-path]").getAttribute("data-native-path");
  if (receivedPath !== expectedPath || !launchPaths.includes(expectedPath)) {
    throw new Error(`Deep link resolved to ${receivedPath || "nothing"}.`);
  }
  const appFrame = page.frames().find((frame) => frame.url().includes("/apps/design-studio/"));
  if (!appFrame) throw new Error("Base Shell did not mount the real Design Studio iframe.");
  process.stdout.write(`${JSON.stringify({
    schema_version: "1",
    kind: "design-studio-shell-native-deep-link-e2e",
    status: "passed",
    shell_route: `/app/design-studio${expectedPath}`,
    native_path: receivedPath,
    isolated_origin: new URL(nativeFrame.url()).origin !== new URL(page.url()).origin,
  }, null, 2)}\n`);
} finally {
  await browser?.close();
  await vite.close();
  await new Promise((resolve) => nativeServer.close(resolve));
}

function collectBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
}

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
}

function useInstalledBrowserCache() {
  if (process.env.PLAYWRIGHT_BROWSERS_PATH) return;
  const cache = path.join(os.userInfo().homedir, ".cache/ms-playwright");
  process.env.PLAYWRIGHT_BROWSERS_PATH = cache;
}
