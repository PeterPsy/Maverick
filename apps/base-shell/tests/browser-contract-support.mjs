import { spawn } from "node:child_process";
import { accessSync, constants } from "node:fs";

export function browserExecutable() {
  const candidates = [
    process.env.MAVERICK_BROWSER_BIN,
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
  ].filter(Boolean);
  return candidates.find((candidate) => {
    try {
      accessSync(candidate, constants.X_OK);
      return true;
    } catch {
      return false;
    }
  }) || null;
}

export function runBrowser(browser, args, timeoutMs = 15_000) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(browser, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    const timeout = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error("Cross-origin browser test timed out."));
    }, timeoutMs);
    child.once("exit", (code) => {
      clearTimeout(timeout);
      resolveRun({ code, stderr, stdout });
    });
  });
}

export function listen(server) {
  return new Promise((resolveOrigin, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("Browser test server did not expose a TCP address."));
        return;
      }
      resolveOrigin(`http://127.0.0.1:${address.port}`);
    });
  });
}

export function close(server) {
  return new Promise((resolveClose) => {
    if (!server.listening) {
      resolveClose();
      return;
    }
    server.close(() => resolveClose());
  });
}

export function send(response, body, contentType, status = 200, headers = {}) {
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "Content-Type": contentType,
    ...headers,
  });
  response.end(body);
}

export function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}
