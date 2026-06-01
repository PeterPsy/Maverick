#!/usr/bin/env node
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const packageJson = require("../package.json");
const pinnedPlaywrightVersion = packageJson.dependencies?.playwright;

if (!pinnedPlaywrightVersion) {
  throw new Error("apps/browser/package.json must pin the playwright dependency.");
}

let playwrightPackagePath;
try {
  playwrightPackagePath = require.resolve("playwright/package.json");
} catch (error) {
  throw new Error("Run npm ci in apps/browser before starting the local Playwright server.");
}

const localPlaywright = require(playwrightPackagePath);
if (localPlaywright.version !== pinnedPlaywrightVersion) {
  throw new Error(
    `Local Playwright version ${localPlaywright.version} does not match pinned version ${pinnedPlaywrightVersion}.`,
  );
}

const host = process.env.MAVERICK_BROWSER_PLAYWRIGHT_HOST || "127.0.0.1";
const port = process.env.MAVERICK_BROWSER_PLAYWRIGHT_PORT || "3100";
const cliPath = join(dirname(playwrightPackagePath), "cli.js");
const args = [cliPath, "run-server", "--host", host, "--port", port];

if (process.argv.includes("--print")) {
  process.stdout.write(`${[process.execPath, ...args].join(" ")}\n`);
  process.exit(0);
}

const child = spawn(process.execPath, args, { stdio: "inherit" });
child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  }
  process.exit(code ?? 1);
});
