import assert from "node:assert/strict";
import {copyFile, mkdir, mkdtemp, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {APP_ROOT, readJson} from "../../scripts/compliance/supply-chain-lib.mjs";
import {
  scanReleaseArtifact,
  validateArchiveEntries,
} from "../../scripts/compliance/verify-release-artifact.mjs";

const fixture = await readJson(path.join(APP_ROOT, "tests/fixtures/supply-chain-negative-cases.json"));

async function withTemporaryDirectory(callback) {
  const directory = await mkdtemp(path.join(tmpdir(), "video-studio-release-test-"));
  try {
    await callback(directory);
  } finally {
    await rm(directory, {recursive: true, force: true});
  }
}

test("frontend-only bundle passes the redistribution gate", async () => {
  await withTemporaryDirectory(async (directory) => {
    await writeFile(path.join(directory, "index.html"), "<!doctype html><title>Video Studio</title>");
    assert.deepEqual(await scanReleaseArtifact(directory), []);
  });
});

test("compositor and FFmpeg payloads fail the release gate", async () => {
  await withTemporaryDirectory(async (directory) => {
    for (const relative of fixture.release_payload_paths) {
      const target = path.join(directory, relative);
      await mkdir(path.dirname(target), {recursive: true});
      await writeFile(target, "fixture only");
    }
    const findings = await scanReleaseArtifact(directory);
    assert.ok(findings.some((item) => item.kind === "remotion-compositor"));
    assert.ok(findings.filter((item) => item.kind === "embedded-media-binary").length >= 2);
  });
});

test("nested container tar payload fails the release gate", async () => {
  await withTemporaryDirectory(async (directory) => {
    const layerRoot = path.join(directory, "layer-root");
    const binary = path.join(layerRoot, "usr/bin/ffmpeg");
    await mkdir(path.dirname(binary), {recursive: true});
    await writeFile(binary, "fixture only");
    const layerTar = path.join(directory, "layer.tar");
    const outerTar = path.join(directory, "container.tar");
    let result = spawnSync("tar", ["-cf", layerTar, "-C", layerRoot, "."], {encoding: "utf8", shell: false});
    assert.equal(result.status, 0, result.stderr);
    result = spawnSync("tar", ["-cf", outerTar, "-C", directory, "layer.tar"], {encoding: "utf8", shell: false});
    assert.equal(result.status, 0, result.stderr);
    const findings = await scanReleaseArtifact(outerTar);
    assert.ok(findings.some((item) => item.kind === "embedded-media-binary"));
  });
});

test("renaming an inventoried compositor binary does not bypass the gate", async () => {
  await withTemporaryDirectory(async (directory) => {
    await copyFile(
      path.join(APP_ROOT, "node_modules/@remotion/compositor-linux-x64-gnu/ffmpeg"),
      path.join(directory, "innocent-worker-name"),
    );
    const findings = await scanReleaseArtifact(directory);
    assert.ok(findings.some((item) => item.kind === "known-blocked-payload"));
  });
});

test("unsafe archive paths fail closed before extraction", () => {
  assert.throws(() => validateArchiveEntries(["../../escape"]), /unsafe path/);
  assert.throws(() => validateArchiveEntries(["/absolute/escape"]), /unsafe path/);
});
