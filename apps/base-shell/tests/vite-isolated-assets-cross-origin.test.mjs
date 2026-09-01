import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createServer } from "node:http";
import { extname, resolve } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";
import { gzipSync } from "node:zlib";
import { build } from "vite";

import { maverickFrontendAssets } from "../../../scripts/vite-frontend-assets.mjs";
import { maverickIsolatedFrameAssetUrls } from "../../../scripts/vite-isolated-frame-assets.mjs";
import {
  browserExecutable,
  close,
  escapeRegExp,
  listen,
  runBrowser,
  send,
} from "./browser-contract-support.mjs";

const APP_BASE = "/apps/vite-isolated-fixture/";
const COMPRESSIBLE_EXTENSIONS = new Set([".css", ".js", ".mjs", ".svg", ".wasm"]);

test("a production Vite bundle keeps runtime assets on the cacheable platform origin", async (context) => {
  const browser = browserExecutable();
  if (!browser) {
    context.skip("Chromium or Chrome is required for the cross-origin browser contract.");
    return;
  }

  const project = mkdtempSync(resolve(tmpdir(), "maverick-vite-isolated-"));
  const profile = mkdtempSync(resolve(tmpdir(), "maverick-vite-browser-"));
  const dist = resolve(project, "dist");
  context.after(() => {
    rmSync(project, { force: true, recursive: true });
    rmSync(profile, { force: true, recursive: true });
  });
  writeFixture(project);
  await build({
    base: APP_BASE,
    build: {
      assetsInlineLimit: 0,
      emptyOutDir: true,
      outDir: dist,
      rollupOptions: { input: resolve(project, "index.html") },
    },
    logLevel: "silent",
    plugins: [maverickIsolatedFrameAssetUrls(), maverickFrontendAssets()],
    root: project,
  });

  const manifest = JSON.parse(readFileSync(resolve(dist, "maverick-frontend-assets.json"), "utf8"));
  const immutablePaths = manifest.immutable.map(({ path }) => path);
  assert.deepEqual(
    [".mjs", ".mp3", ".svg", ".wasm"].filter((extension) =>
      !immutablePaths.some((path) => path.endsWith(extension))),
    [],
    JSON.stringify(immutablePaths),
  );
  const builtJavaScript = immutablePaths
    .filter((path) => path.endsWith(".js"))
    .map((path) => readFileSync(resolve(dist, path), "utf8"))
    .join("\n");
  assert.doesNotMatch(builtJavaScript, /\/apps\/vite-isolated-fixture\/assets\//u);
  assert.match(builtJavaScript, /import\.meta\.url/u);

  const platformServer = createServer();
  const isolatedServer = createServer();
  const platformRequests = [];
  const isolatedAssetRequests = [];
  try {
    const platformOrigin = await listen(platformServer);
    const isolatedOrigin = await listen(isolatedServer);
    const immutableRecords = new Map(
      manifest.immutable.map((record) => [`${APP_BASE}${record.path}`, record]),
    );
    const isolatedHtml = rewriteEntryHtml(
      readFileSync(resolve(dist, "index.html"), "utf8"),
      platformOrigin,
    );

    platformServer.on("request", (request, response) => {
      const pathname = new URL(request.url || "/", platformOrigin).pathname;
      const record = immutableRecords.get(pathname);
      if (!record) {
        send(response, "not found", "text/plain; charset=utf-8", 404);
        return;
      }
      const extension = extname(record.path).toLowerCase();
      const acceptsGzip = /(?:^|,)\s*gzip(?:\s*[,;]|$)/iu.test(request.headers["accept-encoding"] || "");
      const encoded = acceptsGzip && COMPRESSIBLE_EXTENSIONS.has(extension);
      const source = readFileSync(resolve(dist, record.path));
      platformRequests.push({
        acceptEncoding: request.headers["accept-encoding"] || "",
        encoded,
        pathname,
      });
      const headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=31536000, immutable",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "X-Content-Type-Options": "nosniff",
      };
      if (encoded) {
        headers["Content-Encoding"] = "gzip";
        headers.Vary = "Accept-Encoding";
      }
      send(response, encoded ? gzipSync(source) : source, contentType(extension), 200, headers);
    });
    isolatedServer.on("request", (request, response) => {
      const pathname = new URL(request.url || "/", isolatedOrigin).pathname;
      if (pathname === "/" || pathname === "/second") {
        send(response, isolatedHtml, "text/html; charset=utf-8");
        return;
      }
      if (pathname.startsWith(APP_BASE)) isolatedAssetRequests.push(pathname);
      send(response, "not found", "text/plain; charset=utf-8", 404);
    });

    const result = await runBrowser(browser, [
      "--headless=new",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      `--user-data-dir=${profile}`,
      "--virtual-time-budget=10000",
      "--dump-dom",
      `${isolatedOrigin}/`,
    ], 20_000);

    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stdout, /data-result="pass"/u, result.stdout);
    assert.match(result.stdout, /data-round="second"/u, result.stdout);
    assert.match(
      result.stdout,
      new RegExp(`data-document-origin="${escapeRegExp(isolatedOrigin)}"`, "u"),
      result.stdout,
    );
    assert.match(
      result.stdout,
      new RegExp(`data-asset-origin="${escapeRegExp(platformOrigin)}"`, "u"),
      result.stdout,
    );
    assert.deepEqual(isolatedAssetRequests, []);

    for (const record of manifest.immutable) {
      const pathname = `${APP_BASE}${record.path}`;
      const requests = platformRequests.filter((request) => request.pathname === pathname);
      assert.equal(requests.length, 1, `${pathname} was transferred ${requests.length} times`);
      if (COMPRESSIBLE_EXTENSIONS.has(extname(record.path).toLowerCase())) {
        assert.equal(requests[0].encoded, true, `${pathname} was not transferred with gzip`);
      }
    }
  } finally {
    await Promise.all([close(platformServer), close(isolatedServer)]);
  }
});

function rewriteEntryHtml(html, platformOrigin) {
  return html.replace(
    /(?<prefix>\b(?:src|href)\s*=\s*["'])(?<path>\/apps\/vite-isolated-fixture\/assets\/[^"']+)/giu,
    (_match, _prefix, _path, _offset, _input, groups) => `${groups.prefix}${platformOrigin}${groups.path}`,
  );
}

function contentType(extension) {
  return {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
  }[extension] || "application/octet-stream";
}

function writeFixture(project) {
  const source = resolve(project, "src");
  mkdirSync(source, { recursive: true });
  writeFileSync(resolve(project, "index.html"), `<!doctype html>
<html><head><meta charset="utf-8"><title>Vite isolated fixture</title></head>
<body data-result="pending"><script type="module" src="/src/main.js"></script></body></html>`);
  writeFileSync(resolve(source, "main.js"), `
import audioUrl from "./count-down.mp3?url";
import imageUrl from "./runtime-image.svg?url";
import wasmUrl from "./decoder.wasm?url";
import workerUrl from "./pdf.worker.mjs?url";

const imageReady = new Promise((resolve, reject) => {
  const image = new Image();
  image.onload = resolve;
  image.onerror = () => reject(new Error("image failed"));
  image.src = imageUrl;
  document.body.append(image);
});
const workerReady = new Promise((resolve, reject) => {
  const wrapper = URL.createObjectURL(new Blob([
    "import " + JSON.stringify(workerUrl) + ";",
  ], { type: "text/javascript" }));
  const worker = new Worker(wrapper, { type: "module" });
  const timeout = setTimeout(() => reject(new Error("worker timed out")), 3000);
  worker.onmessage = (event) => {
    clearTimeout(timeout);
    URL.revokeObjectURL(wrapper);
    worker.terminate();
    event.data === "worker-ready" ? resolve() : reject(new Error("worker failed"));
  };
  worker.onerror = reject;
});

Promise.all([
  import("./lazy.js"),
  fetch(audioUrl).then((response) => { if (!response.ok) throw new Error("audio failed"); }),
  fetch(wasmUrl).then((response) => { if (!response.ok) throw new Error("wasm failed"); }),
  imageReady,
  workerReady,
]).then(([lazy]) => {
  if (lazy.lazyValue !== "lazy-ready") throw new Error("lazy import failed");
  const origins = [audioUrl, imageUrl, wasmUrl, workerUrl].map((url) => new URL(url).origin);
  if (new Set(origins).size !== 1) throw new Error("asset origins diverged");
  document.body.dataset.assetOrigin = origins[0];
  document.body.dataset.documentOrigin = location.origin;
  if (sessionStorage.getItem("maverick-vite-round") === null) {
    sessionStorage.setItem("maverick-vite-round", "second");
    location.replace("/second");
    return;
  }
  document.body.dataset.result = "pass";
  document.body.dataset.round = "second";
}).catch((error) => {
  document.body.dataset.result = "fail";
  document.body.dataset.error = String(error?.message || error);
});
`);
  writeFileSync(resolve(source, "lazy.js"), `import "./lazy.css"; export const lazyValue = "lazy-ready";`);
  writeFileSync(resolve(source, "lazy.css"), `.fixture { color: rgb(1 2 3); }\n`.repeat(80));
  writeFileSync(resolve(source, "pdf.worker.mjs"), `self.postMessage("worker-ready");\n${"// worker payload\n".repeat(100)}`);
  writeFileSync(resolve(source, "count-down.mp3"), Buffer.concat([Buffer.from("ID3"), Buffer.alloc(4096, 7)]));
  writeFileSync(resolve(source, "decoder.wasm"), Buffer.concat([Buffer.from([0, 97, 115, 109, 1, 0, 0, 0]), Buffer.alloc(4096)]));
  writeFileSync(
    resolve(source, "runtime-image.svg"),
    `<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2"/>${"<!-- payload -->".repeat(100)}</svg>`,
  );
}
