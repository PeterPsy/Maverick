import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { build } from "vite";

import { maverickFrontendAssets } from "../../../scripts/vite-frontend-assets.mjs";

test("shell build identity covers worker logic and the injected verified precache", async (context) => {
  const root = mkdtempSync(resolve(tmpdir(), "maverick-shell-precache-"));
  context.after(() => rmSync(root, { force: true, recursive: true }));
  const sourceRoot = resolve(root, "src");
  const publicRoot = resolve(sourceRoot, "public");
  const outDir = resolve(root, "dist");
  mkdirSync(publicRoot, { recursive: true });
  writeFileSync(resolve(sourceRoot, "index.html"), '<script type="module" src="./main.js"></script>');
  writeFileSync(resolve(sourceRoot, "main.js"), 'document.body.dataset.ready = "yes";');
  writeWorkerTemplate(publicRoot, "v1");

  const first = await runBuild({ outDir, sourceRoot });
  const firstWorker = readFileSync(resolve(outDir, "sw.js"), "utf8");
  assert.equal(first.schema, "maverick.frontend-assets.v2");
  assert.equal(first.navigation_fallback, "index.html");
  assert.ok(first.precache.some(({ url }) => url === "/"));
  assert.ok(first.precache.some(({ url }) => url.startsWith("/shell/assets/")));
  assert.ok(firstWorker.includes(first.build_id));
  assert.ok(!firstWorker.includes("__MAVERICK_"));
  assert.equal(
    first.revalidated.find(({ path }) => path === "sw.js").sha256,
    createHash("sha256").update(firstWorker).digest("hex"),
  );

  writeWorkerTemplate(publicRoot, "v2");
  const changedWorker = await runBuild({ outDir, sourceRoot });
  assert.notEqual(changedWorker.build_id, first.build_id, "worker-only changes require a distinct cache identity");

  const changedSelection = await runBuild({ includeAlias: true, outDir, sourceRoot });
  assert.notEqual(changedSelection.build_id, changedWorker.build_id, "precache selection is part of build identity");
});

async function runBuild({ includeAlias = false, outDir, sourceRoot }) {
  const routes = [{ url: "/", path: "index.html" }];
  if (includeAlias) routes.push({ url: "/shell", path: "index.html" });
  await build({
    base: "/shell/",
    configFile: false,
    logLevel: "silent",
    plugins: [maverickFrontendAssets({
      navigationFallback: "index.html",
      serviceWorkerPath: "sw.js",
      precache: { immutable: true, routes },
    })],
    root: sourceRoot,
    build: { emptyOutDir: true, outDir },
  });
  return JSON.parse(readFileSync(resolve(outDir, "maverick-frontend-assets.json"), "utf8"));
}

function writeWorkerTemplate(publicRoot, version) {
  writeFileSync(
    resolve(publicRoot, "sw.js"),
    `const VERSION = "${version}:__MAVERICK_BUILD_ID__";\nconst PRECACHE = __MAVERICK_PRECACHE_MANIFEST__;\nconst IMMUTABLE = __MAVERICK_IMMUTABLE_ASSETS__;\nconst NAVIGATION_FALLBACK = __MAVERICK_NAVIGATION_FALLBACK_URL__;\n`,
  );
}
