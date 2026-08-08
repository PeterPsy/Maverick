import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import {APP_ROOT, readJson} from "../../scripts/compliance/supply-chain-lib.mjs";
import {
  validateFfmpegManifest,
  verifyInstalledToolchain,
} from "../../scripts/toolchain/verify-ffmpeg.mjs";

const manifest = await readJson(path.join(APP_ROOT, "compliance/ffmpeg-host-manifest.json"));
const fixture = await readJson(path.join(APP_ROOT, "tests/fixtures/supply-chain-negative-cases.json"));

test("accepted host FFmpeg and ffprobe match the content-addressed manifest", async () => {
  assert.deepEqual(await verifyInstalledToolchain(manifest), []);
});

test("checksum mutation fails installed capability verification", async () => {
  const mutated = structuredClone(manifest);
  mutated.binaries.ffmpeg.sha256 = fixture.bad_sha256;
  assert.match((await verifyInstalledToolchain(mutated)).join("\n"), /checksum mismatch/);
});

test("build and license identity mutations fail manifest validation", () => {
  const mutated = structuredClone(manifest);
  mutated.build.configuration = mutated.build.configuration.filter((flag) => flag !== fixture.missing_build_flag);
  mutated.license.classification = "LGPL-2.1-or-later";
  const errors = validateFfmpegManifest(mutated).join("\n");
  assert.match(errors, /classified as GPL-2.0-or-later/);
  assert.match(errors, /missing --enable-gpl/);
});

test("non-array or shell invocation capability fails closed", () => {
  const mutated = structuredClone(manifest);
  mutated.capability.invocation.mode = fixture.unsafe_invocation_mode;
  mutated.capability.invocation.shell = true;
  const errors = validateFfmpegManifest(mutated).join("\n");
  assert.match(errors, /argv array/);
  assert.match(errors, /disable shell execution/);
});
