#!/usr/bin/env node

import {readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {
  APP_ROOT,
  assertInstalledCompositors,
  assertLicenseFiles,
  inspectSupplyChain,
  integrityHash,
  loadSupplyChainInputs,
  npmPurl,
  readJson,
  sha256File,
} from "./supply-chain-lib.mjs";
import {validateFfmpegManifest} from "../toolchain/verify-ffmpeg.mjs";

const inputs = await loadSupplyChainInputs();
const inspection = inspectSupplyChain(inputs);
inspection.errors.push(...(await assertLicenseFiles(APP_ROOT, inputs.policy)));
inspection.errors.push(...(await assertInstalledCompositors(APP_ROOT, inputs.compositorInventory)));
const ffmpegManifestPath = path.join(APP_ROOT, "compliance/ffmpeg-host-manifest.json");
const ffmpegManifest = await readJson(ffmpegManifestPath);
inspection.errors.push(...validateFfmpegManifest(ffmpegManifest));
if (inspection.errors.length > 0) {
  throw new Error(`refusing to generate compliance baseline:\n- ${inspection.errors.join("\n- ")}`);
}

const inventoryByName = new Map(inputs.compositorInventory.packages.map((item) => [item.name, item]));

function sbomLicense(component) {
  if (inputs.policy.licenses.allowed_spdx_expressions.includes(component.license)) {
    return [{expression: component.license}];
  }
  if (component.license && component.license !== "SEE LICENSE IN LICENSE.md") {
    return [{license: {name: component.license}}];
  }
  if (component.name.startsWith("@remotion/compositor-")) {
    return [{license: {name: "NOASSERTION"}}];
  }
  return [{license: {name: "Remotion License"}}];
}

function nestedBinaryComponents(component) {
  const inventory = inventoryByName.get(component.name);
  return (inventory?.embedded_files ?? []).map((file) => ({
    type: "file",
    "bom-ref": `embedded:${component.name}@${component.version}/${file.path}`,
    name: file.path,
    hashes: [{alg: "SHA-256", content: file.sha256.toUpperCase()}],
    properties: [
      {name: "maverick:embedded-in", value: `${component.name}@${component.version}`},
      {name: "maverick:redistribution-allowed", value: "false"},
      {name: "maverick:bytes", value: String(file.bytes)},
    ],
  }));
}

const sbomComponents = inspection.components.map((component) => {
  const integrity = integrityHash(component.integrity);
  const result = {
    type: "library",
    "bom-ref": `${npmPurl(component.name, component.version)}?lock_path=${encodeURIComponent(component.lockPath)}`,
    group: component.name.startsWith("@") ? component.name.split("/")[0] : undefined,
    name: component.name.startsWith("@") ? component.name.split("/")[1] : component.name,
    version: component.version,
    purl: npmPurl(component.name, component.version),
    licenses: sbomLicense(component),
    hashes: integrity ? [{alg: "SHA-512", content: integrity}] : undefined,
    externalReferences: component.resolved
      ? [{type: "distribution", url: component.resolved}]
      : undefined,
    properties: [
      {name: "maverick:npm-lock-path", value: component.lockPath},
      {name: "maverick:optional", value: String(component.optional === true)},
      ...(component.name.startsWith("@remotion/compositor-")
        ? [
            {name: "maverick:license-review", value: "NOASSERTION-development-only"},
            {name: "maverick:release-redistribution", value: "blocked"},
          ]
        : []),
    ],
  };
  const nested = nestedBinaryComponents(component);
  if (nested.length > 0) result.components = nested;
  for (const [key, value] of Object.entries(result)) {
    if (value === undefined) delete result[key];
  }
  return result;
});

const sbom = {
  bomFormat: "CycloneDX",
  specVersion: "1.5",
  version: 1,
  metadata: {
    timestamp: `${inputs.policy.snapshot_date}T00:00:00Z`,
    tools: [{vendor: "Maverick", name: "video-studio compliance baseline generator", version: "1"}],
    component: {
      type: "application",
      "bom-ref": npmPurl(inputs.packageManifest.name, inputs.packageManifest.version),
      name: inputs.packageManifest.name,
      version: inputs.packageManifest.version,
      purl: npmPurl(inputs.packageManifest.name, inputs.packageManifest.version),
    },
    properties: [
      {name: "maverick:compliance-status", value: "development-baseline-not-release-approval"},
      {name: "maverick:remotion-version", value: inputs.policy.remotion.approved_version},
      {name: "maverick:embedded-compositor-redistribution", value: "blocked"},
      {name: "maverick:embedded-ffmpeg-redistribution", value: "blocked"},
      {name: "maverick:approved-model-count", value: String(inputs.modelInventory.models.length)},
    ],
  },
  components: sbomComponents,
};

const sbomPath = path.join(APP_ROOT, "compliance/sbom.cdx.json");
await writeFile(sbomPath, `${JSON.stringify(sbom, null, 2)}\n`);

const packageRows = inspection.components.map((component) => {
  const license = component.license ?? "NOASSERTION (development-only governed exception)";
  return `| \`${component.name}\` | \`${component.version}\` | ${license.replaceAll("|", "\\|")} |`;
});
const compositorRows = inputs.compositorInventory.packages.map(
  (item) =>
    `| \`${item.name}\` | \`${item.archive_sha256}\` | ${item.embedded_files.length} | NOASSERTION; redistribution blocked |`,
);
const remotionLicense = await readFile(path.join(APP_ROOT, "node_modules/remotion/LICENSE.md"), "utf8");
const notices = `# Video Studio Third-Party Notices — Development Baseline

> **Not a release compliance approval.** This regenerable baseline inventories the locked
> development tree. Release, bundle, installer, image, and container redistribution remains
> blocked while the Remotion compositor packages and their embedded media binaries lack an
> approved redistribution decision, complete corresponding-source process, and final notices.

Generated from \`package-lock.json\` on the fixed policy snapshot date
\`${inputs.policy.snapshot_date}\`. Governing decisions are
\`docs/adr/0007-video-studio-remotion-4-license-and-version.md\` and
\`docs/adr/0008-video-studio-ffmpeg-build-and-distribution.md\`.

## Material unresolved redistribution risk

\`@remotion/renderer@${inputs.policy.remotion.approved_version}\` declares seven optional native
compositor packages. Their published metadata and tarballs contain no adequate license
declaration, while every tarball embeds FFmpeg, ffprobe, native Remotion code, and media
libraries. The inspected Linux x64 GNU FFmpeg build is GPL-enabled and includes libfdk-aac,
libx264, and libx265. The packages are permitted only in this explicitly inventoried local
development baseline and are rejected by the release-artifact gate.

| Package | Tarball SHA-256 | Embedded native files | Release status |
|---|---|---:|---|
${compositorRows.join("\n")}

## External host FFmpeg

Video Studio requires the operator-installed Ubuntu package
\`ffmpeg 7:7.1.1-1ubuntu1.3 amd64\` as a governed external process. The accepted host build is
GPL-2.0-or-later because it enables GPL, libx264, and libx265. Maverick does not embed or
redistribute that binary. See the machine-readable host manifest and FFmpeg's legal checklist:
<https://ffmpeg.org/legal.html>.

## Locked npm inventory

This table is an inventory and license-review input. SPDX identifiers do not replace delivery
of license texts, attribution, source offers, or other obligations that a final distribution
review may require.

| Package | Version | Declared license |
|---|---:|---|
${packageRows.join("\n")}

## Model inventory

No model artifacts are approved or installed by this baseline. Adding a model requires an
immutable revision, separate code and weights licenses, model card, tokenizer version, and
SHA-256 for every installed artifact; unreviewed or moving-tag models fail policy.

## Remotion License (verbatim from the pinned package)

Source file SHA-256:
\`${inputs.policy.remotion.license_file_sha256}\`.

${remotionLicense.trim()}
`;
const noticesPath = path.join(APP_ROOT, "compliance/THIRD-PARTY-NOTICES.md");
await writeFile(noticesPath, notices);

const trackedInputs = [
  "package.json",
  "package-lock.json",
  "compliance/supply-chain-policy.json",
  "compliance/remotion-compositor-inventory.json",
  "compliance/ffmpeg-host-manifest.json",
  "compliance/model-inventory.json",
  "scripts/compliance/generate-baseline.mjs",
  "scripts/compliance/inventory-remotion-compositors.mjs",
  "scripts/compliance/model-policy.mjs",
  "scripts/compliance/supply-chain-lib.mjs",
  "scripts/compliance/verify-release-artifact.mjs",
  "scripts/compliance/verify-supply-chain.mjs",
  "scripts/toolchain/verify-ffmpeg.mjs",
  "../../docs/adr/0007-video-studio-remotion-4-license-and-version.md",
  "../../docs/adr/0008-video-studio-ffmpeg-build-and-distribution.md",
];
const provenance = {
  schema_version: 1,
  snapshot_date: inputs.policy.snapshot_date,
  status: "development baseline; not signed release provenance or legal approval",
  generator: "scripts/compliance/generate-baseline.mjs",
  runtime: inputs.policy.node,
  sources: [
    "package-lock.json integrity-pinned npm registry artifacts",
    "compliance/remotion-compositor-inventory.json",
    "compliance/ffmpeg-host-manifest.json",
    "https://github.com/remotion-dev/remotion/blob/v4.0.506/LICENSE.md",
    "https://ffmpeg.org/legal.html"
  ],
  input_sha256: Object.fromEntries(
    await Promise.all(trackedInputs.map(async (relative) => [relative, await sha256File(path.join(APP_ROOT, relative))])),
  ),
  output_sha256: {
    "compliance/sbom.cdx.json": await sha256File(sbomPath),
    "compliance/THIRD-PARTY-NOTICES.md": await sha256File(noticesPath),
  },
  package_count: inspection.components.length,
  embedded_compositor_package_count: inputs.compositorInventory.packages.length,
  approved_model_count: inputs.modelInventory.models.length,
  release_blockers: [
    "Remotion compositor packages have NOASSERTION license metadata and embed FFmpeg/native libraries.",
    "No ADR currently authorizes redistribution of the compositor or an FFmpeg-containing release artifact.",
    "This baseline is unsigned and is not a vulnerability attestation or final legal review."
  ],
};
await writeFile(path.join(APP_ROOT, "compliance/provenance.json"), `${JSON.stringify(provenance, null, 2)}\n`);
console.log(`Generated development SBOM, notices, and provenance for ${inspection.components.length} packages.`);
