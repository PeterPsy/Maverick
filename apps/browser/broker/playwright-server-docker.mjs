#!/usr/bin/env node
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";

const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const pinnedPlaywrightVersion = packageJson.dependencies?.playwright;

const version = process.env.MAVERICK_BROWSER_PLAYWRIGHT_VERSION || pinnedPlaywrightVersion;
if (!version) {
  throw new Error("apps/browser/package.json must pin the playwright dependency.");
}
const image = process.env.MAVERICK_BROWSER_PLAYWRIGHT_IMAGE || `mcr.microsoft.com/playwright:v${version}-noble`;
const hostPort = process.env.MAVERICK_BROWSER_PLAYWRIGHT_PORT || "3100";
const containerPort = "3000";

const args = [
  "run",
  "--rm",
  "--init",
  "--pull=missing",
  "--add-host",
  "hostmachine:host-gateway",
  "--user",
  "pwuser",
  "--workdir",
  "/home/pwuser",
  "-p",
  `${hostPort}:${containerPort}`,
  image,
  "npx",
  "--yes",
  `playwright@${version}`,
  "run-server",
  "--host",
  "0.0.0.0",
  "--port",
  containerPort,
];

if (process.argv.includes("--print")) {
  process.stdout.write(`${["docker", ...args].join(" ")}\n`);
  process.exit(0);
}

const child = spawn("docker", args, { stdio: "inherit" });
child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  }
  process.exit(code ?? 1);
});
