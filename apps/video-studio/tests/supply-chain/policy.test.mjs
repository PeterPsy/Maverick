import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import {
  APP_ROOT,
  assertInstalledCompositors,
  assertLicenseFiles,
  inspectSupplyChain,
  loadSupplyChainInputs,
  readJson,
} from "../../scripts/compliance/supply-chain-lib.mjs";

const fixture = await readJson(path.join(APP_ROOT, "tests/fixtures/supply-chain-negative-cases.json"));
const baseline = await loadSupplyChainInputs();

function cloneInputs() {
  return structuredClone(baseline);
}

test("approved lockfile, inventory, and license files pass policy", async () => {
  const result = inspectSupplyChain(baseline);
  result.errors.push(...(await assertLicenseFiles(APP_ROOT, baseline.policy)));
  result.errors.push(...(await assertInstalledCompositors(APP_ROOT, baseline.compositorInventory)));
  assert.deepEqual(result.errors, []);
  assert.equal(result.components.length, 278);
});

test("Remotion dependency ranges fail closed", () => {
  const inputs = cloneInputs();
  inputs.packageManifest.dependencies.remotion = fixture.remotion_range;
  inputs.lockfile.packages[""].dependencies.remotion = fixture.remotion_range;
  assert.match(inspectSupplyChain(inputs).errors.join("\n"), /must use exact version/);
});

test("misaligned transitive Remotion versions fail closed", () => {
  const inputs = cloneInputs();
  inputs.lockfile.packages["node_modules/@remotion/renderer"].version = fixture.misaligned_version;
  assert.match(inspectSupplyChain(inputs).errors.join("\n"), /misaligned/);
});

test("forbidden transitions package fails whether direct or locked", () => {
  const inputs = cloneInputs();
  inputs.packageManifest.dependencies[fixture.forbidden_package] = baseline.policy.remotion.approved_version;
  inputs.lockfile.packages[`node_modules/${fixture.forbidden_package}`] = {
    version: baseline.policy.remotion.approved_version,
    integrity: "sha512-Zml4dHVyZQ==",
    license: "UNLICENSED",
  };
  const errors = inspectSupplyChain(inputs).errors.join("\n");
  assert.match(errors, /forbidden package @remotion\/transitions/);
});

test("unknown and ungoverned GPL license metadata fail closed", () => {
  const unknownInputs = cloneInputs();
  unknownInputs.lockfile.packages[`node_modules/${fixture.unknown_license_package}`] = {
    version: "1.0.0",
    integrity: "sha512-Zml4dHVyZQ==",
  };
  assert.match(inspectSupplyChain(unknownInputs).errors.join("\n"), /UNKNOWN\/absent/);

  const gplInputs = cloneInputs();
  gplInputs.lockfile.packages["node_modules/fixture-gpl"] = {
    version: "1.0.0",
    integrity: "sha512-Zml4dHVyZQ==",
    license: fixture.gpl_license,
  };
  assert.match(inspectSupplyChain(gplInputs).errors.join("\n"), /blocked GPL/);
});

test("compositor provenance checksum omissions fail closed", () => {
  const inputs = cloneInputs();
  inputs.compositorInventory.packages[0].archive_sha256 = "";
  assert.match(inspectSupplyChain(inputs).errors.join("\n"), /missing archive or embedded FFmpeg evidence/);
});

test("moving model revisions and incomplete model provenance fail closed", () => {
  const inputs = cloneInputs();
  inputs.modelInventory.models.push({
    id: "fixture-model",
    source_url: "https://models.example.invalid/fixture",
    model_card_url: "https://models.example.invalid/fixture/card",
    revision: "latest",
    code_license: "MIT",
    weights_license: "",
    tokenizer_version: "1.0.0",
    files: [{path: "weights.bin", sha256: "not-a-digest"}],
  });
  const errors = inspectSupplyChain(inputs).errors.join("\n");
  assert.match(errors, /immutable exact revision/);
  assert.match(errors, /weights_license/);
  assert.match(errors, /without valid path and sha256/);
});

test("generated SBOM records all packages and embedded compositor files", async () => {
  const sbom = JSON.parse(await readFile(path.join(APP_ROOT, "compliance/sbom.cdx.json"), "utf8"));
  assert.equal(sbom.metadata.properties.find((item) => item.name === "maverick:compliance-status").value, "development-baseline-not-release-approval");
  assert.equal(sbom.components.length, 278);
  const compositor = sbom.components.find(
    (component) => component.purl === "pkg:npm/%40remotion/compositor-linux-x64-gnu@4.0.506",
  );
  assert.ok(compositor.components.some((component) => component.name === "ffmpeg"));
  assert.ok(compositor.components.some((component) => component.name === "ffprobe"));
});
