import assert from "node:assert/strict";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { build } from "vite";

import { maverickFrontendAssets } from "../../../scripts/vite-frontend-assets.mjs";

test("App Store changes asset filename and digest when one source byte changes", async (context) => {
  const temporaryRoot = mkdtempSync(resolve(tmpdir(), "maverick-app-store-hash-"));
  context.after(() => rmSync(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = resolve(temporaryRoot, "src");
  const outDir = resolve(temporaryRoot, "dist");
  cpSync(resolve(import.meta.dirname, "../frontend/src"), sourceRoot, { recursive: true });

  async function runBuild() {
    await build({
      configFile: false,
      logLevel: "silent",
      base: "/apps/app-store/",
      root: sourceRoot,
      plugins: [maverickFrontendAssets()],
      build: {
        outDir,
        emptyOutDir: true,
        rollupOptions: {
          input: {
            app: resolve(sourceRoot, "index.html"),
            "widgets/app-shortcuts/index": resolve(sourceRoot, "widgets/app-shortcuts/index.html"),
          },
        },
      },
    });
    return JSON.parse(readFileSync(resolve(outDir, "maverick-frontend-assets.json"), "utf8"));
  }

  const before = await runBuild();
  const changedPath = resolve(sourceRoot, "assets/main.js");
  const original = readFileSync(changedPath, "utf8");
  const changed = original.replace("Promote to server app", "promote to server app");
  assert.equal(Buffer.byteLength(changed), Buffer.byteLength(original));
  assert.equal([...original].filter((character, index) => character !== changed[index]).length, 1);
  writeFileSync(changedPath, changed);
  const after = await runBuild();

  const beforeJavaScript = new Map(before.immutable.filter(({ path }) => path.endsWith(".js")).map((record) => [record.path, record.sha256]));
  const afterJavaScript = new Map(after.immutable.filter(({ path }) => path.endsWith(".js")).map((record) => [record.path, record.sha256]));
  assert.notDeepEqual(afterJavaScript, beforeJavaScript);
  assert.ok([...beforeJavaScript].some(([path, digest]) => !afterJavaScript.has(path) && ![...afterJavaScript.values()].includes(digest)));
});

test("static Rollup output names that resemble hashes remain revalidated", async (context) => {
  const temporaryRoot = mkdtempSync(resolve(tmpdir(), "maverick-semantic-asset-"));
  context.after(() => rmSync(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = resolve(temporaryRoot, "src");
  const outDir = resolve(temporaryRoot, "dist");
  mkdirSync(sourceRoot);
  writeFileSync(resolve(sourceRoot, "index.html"), '<script type="module" src="./main.js"></script>');
  writeFileSync(resolve(sourceRoot, "main.js"), 'console.log("semantic");');

  await build({
    configFile: false,
    logLevel: "silent",
    root: sourceRoot,
    plugins: [
      {
        name: "static-lookalike-asset",
        buildStart() {
          this.emitFile({ type: "asset", fileName: "assets/copied-cafebabe.svg", source: "<svg/>" });
        },
      },
      maverickFrontendAssets(),
    ],
    build: {
      outDir,
      emptyOutDir: true,
      rollupOptions: { output: { entryFileNames: "assets/app-deadbeef.js" } },
    },
  });

  const manifest = JSON.parse(readFileSync(resolve(outDir, "maverick-frontend-assets.json"), "utf8"));
  assert.ok(manifest.revalidated.some(({ path }) => path === "assets/app-deadbeef.js"));
  assert.ok(manifest.revalidated.some(({ path }) => path === "assets/copied-cafebabe.svg"));
  assert.ok(!manifest.immutable.some(({ path }) => path === "assets/app-deadbeef.js"));
  assert.ok(!manifest.immutable.some(({ path }) => path === "assets/copied-cafebabe.svg"));
});
