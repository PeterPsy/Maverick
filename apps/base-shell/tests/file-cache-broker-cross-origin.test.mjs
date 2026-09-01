import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import ts from "typescript";
import {
  browserExecutable,
  close,
  escapeRegExp,
  listen,
  runBrowser,
  send,
} from "./browser-contract-support.mjs";

test("the Storage broker handshake reaches a parent on a distinct browser origin", async (context) => {
  const browser = browserExecutable();
  if (!browser) {
    context.skip("Chromium or Chrome is required for the cross-origin browser contract.");
    return;
  }

  const protocolSource = readFileSync(
    resolve(import.meta.dirname, "../../../packages/pwa-cache/src/fileCacheBrokerProtocol.ts"),
    "utf8",
  );
  const protocolModule = ts.transpileModule(protocolSource, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const childServer = createServer();
  const shellServer = createServer();
  const profile = mkdtempSync(resolve(tmpdir(), "maverick-broker-browser-"));
  context.after(() => rmSync(profile, { force: true, recursive: true }));

  try {
    const childOrigin = await listen(childServer);
    const shellOrigin = await listen(shellServer);
    childServer.on("request", (request, response) => {
      if (request.url === "/fileCacheBrokerProtocol.js") {
        send(response, protocolModule, "text/javascript; charset=utf-8");
        return;
      }
      if (request.url === "/child.html") {
        send(response, childDocument(shellOrigin), "text/html; charset=utf-8");
        return;
      }
      send(response, "not found", "text/plain; charset=utf-8", 404);
    });
    shellServer.on("request", (request, response) => {
      if (request.url === "/") {
        send(response, shellDocument(childOrigin), "text/html; charset=utf-8");
        return;
      }
      send(response, "not found", "text/plain; charset=utf-8", 404);
    });

    const result = await runBrowser(browser, [
      "--headless=new",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      `--user-data-dir=${profile}`,
      "--virtual-time-budget=3000",
      "--dump-dom",
      `${shellOrigin}/`,
    ]);

    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stdout, /data-result="pass"/u, result.stdout);
    assert.match(result.stdout, /data-source="cache"/u, result.stdout);
    assert.match(result.stdout, new RegExp(`data-child-origin="${escapeRegExp(childOrigin)}"`, "u"));
  } finally {
    await Promise.all([close(childServer), close(shellServer)]);
  }
});

function shellDocument(childOrigin) {
  return `<!doctype html>
<html><body data-result="pending"><iframe id="storage-frame"></iframe>
<script>
  const childOrigin = ${JSON.stringify(childOrigin)};
  const frame = document.querySelector("#storage-frame");
  window.addEventListener("message", (event) => {
    if (event.source !== frame.contentWindow || event.origin !== childOrigin) return;
    if (event.data?.type === "maverick.storage.file-cache.open.v1" && event.ports.length === 1) {
      const port = event.ports[0];
      document.body.dataset.childOrigin = event.origin;
      port.postMessage({
        app_id: "storage",
        request_id: event.data.request_id,
        type: "maverick.storage.file-cache.accepted.v1",
      });
      port.postMessage({
        app_id: "storage",
        blob: new Blob(["cached"], { type: "text/plain" }),
        request_id: event.data.request_id,
        source: "cache",
        status: "ok",
        type: "maverick.storage.file-cache.result.v1",
      });
      return;
    }
    if (event.data?.type === "maverick.test.file-cache-complete") {
      document.body.dataset.result = event.data.ok === true ? "pass" : "fail";
      document.body.dataset.source = String(event.data.source || "none");
    }
  });
  frame.src = childOrigin + "/child.html";
</script></body></html>`;
}

function childDocument(shellOrigin) {
  return `<!doctype html>
<html><head><script>
  Object.defineProperty(window, "__MAVERICK_PLATFORM_ORIGIN__", {
    configurable: false,
    value: ${JSON.stringify(shellOrigin)},
  });
</script></head><body><script type="module">
  import { requestParentFileCacheOpen } from "/fileCacheBrokerProtocol.js";
  const result = await requestParentFileCacheOpen({
    fileId: "file-one",
    sourceVersion: "version-one",
  });
  window.parent.postMessage({
    ok: (await result?.blob.text()) === "cached",
    source: result?.source || "none",
    type: "maverick.test.file-cache-complete",
  }, ${JSON.stringify(shellOrigin)});
</script></body></html>`;
}
