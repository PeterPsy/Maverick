#!/usr/bin/env node

import {createHash} from "node:crypto";
import {readFile, realpath} from "node:fs/promises";
import path from "node:path";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const DEFAULT_MANIFEST = path.join(APP_ROOT, "compliance/ffmpeg-host-manifest.json");

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function buildFlags(output) {
  return output
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("--"));
}

function runExecutable(executable, argv) {
  const result = spawnSync(executable, argv, {
    encoding: "utf8",
    env: {LANG: "C", LC_ALL: "C"},
    maxBuffer: 4 * 1024 * 1024,
    shell: false,
    timeout: 10_000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`${path.basename(executable)} ${argv.join(" ")} failed: ${result.error?.message ?? result.stderr}`);
  }
  return `${result.stdout ?? ""}${result.stderr ?? ""}`;
}

export function validateFfmpegManifest(manifest) {
  const errors = [];
  if (manifest.schema_version !== 1) errors.push("unsupported manifest schema");
  if (manifest.status !== "accepted-local-server-external-process") errors.push("manifest is not an accepted local-server profile");
  if (manifest.distribution?.embedded_or_redistributed !== false) errors.push("manifest must describe a non-embedded external process");
  if (manifest.distribution?.redistribution_allowed !== false) errors.push("FFmpeg redistribution must remain blocked");
  if (manifest.license?.classification !== "GPL-2.0-or-later") errors.push("audited build must be classified as GPL-2.0-or-later");
  if (manifest.capability?.invocation?.mode !== "argv-array") errors.push("FFmpeg invocation must use an argv array");
  if (manifest.capability?.invocation?.shell !== false) errors.push("FFmpeg invocation must disable shell execution");
  if (manifest.capability?.invocation?.trusted_executable_resolution !== "manifest-absolute-path-only") {
    errors.push("executable resolution must be manifest-absolute-path-only");
  }
  if (manifest.capability?.sandbox?.egress !== "deny-by-default") errors.push("sandbox egress must be deny-by-default");
  if (manifest.capability?.sandbox?.process_tree_kill !== true) errors.push("sandbox must terminate the complete process tree");

  for (const binaryName of ["ffmpeg", "ffprobe"]) {
    const binary = manifest.binaries?.[binaryName];
    if (!binary || !path.isAbsolute(binary.absolute_path ?? "")) errors.push(`${binaryName} requires an absolute manifest path`);
    if (!/^[a-f0-9]{64}$/.test(binary?.sha256 ?? "")) errors.push(`${binaryName} requires a sha256 digest`);
    if (!binary?.version_first_line?.startsWith(`${binaryName} version `)) errors.push(`${binaryName} requires an exact version line`);
  }

  const configuration = manifest.build?.configuration ?? [];
  for (const flag of manifest.build?.required_legal_flags ?? []) {
    if (!configuration.includes(flag)) errors.push(`build configuration is missing required legal flag ${flag}`);
  }
  for (const flag of ["--enable-gpl", "--enable-libx264", "--enable-libx265"]) {
    if (!configuration.includes(flag)) errors.push(`audited build identity is missing ${flag}`);
  }
  for (const [name, values] of Object.entries(manifest.capability?.allowlists ?? {})) {
    if (!Array.isArray(values) || values.length === 0) errors.push(`${name} allowlist must be non-empty`);
  }
  return errors;
}

export async function verifyInstalledToolchain(manifest) {
  const errors = validateFfmpegManifest(manifest);
  if (errors.length > 0) return errors;
  for (const binaryName of ["ffmpeg", "ffprobe"]) {
    const binary = manifest.binaries[binaryName];
    try {
      const resolved = await realpath(binary.absolute_path);
      if (resolved !== binary.absolute_path) {
        errors.push(`${binaryName} resolves to ${resolved}, not accepted path ${binary.absolute_path}`);
        continue;
      }
      const content = await readFile(resolved);
      const digest = sha256(content);
      if (digest !== binary.sha256) errors.push(`${binaryName} checksum mismatch: ${digest}`);
      const version = runExecutable(resolved, ["-version"]).split("\n").find(Boolean);
      if (version !== binary.version_first_line) errors.push(`${binaryName} version mismatch: ${version}`);
      const observedFlags = buildFlags(runExecutable(resolved, ["-buildconf"]));
      if (JSON.stringify(observedFlags) !== JSON.stringify(manifest.build.configuration)) {
        errors.push(`${binaryName} build configuration differs from the accepted manifest`);
      }
    } catch (error) {
      errors.push(`${binaryName} verification failed: ${error.message}`);
    }
  }
  return errors;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const manifestPath = process.argv[2] ? path.resolve(process.argv[2]) : DEFAULT_MANIFEST;
  try {
    const manifestBytes = await readFile(manifestPath);
    const manifest = JSON.parse(manifestBytes.toString("utf8"));
    const errors = await verifyInstalledToolchain(manifest);
    if (errors.length > 0) {
      console.error("FFmpeg capability verification failed closed:");
      for (const error of errors) console.error(`- ${error}`);
      process.exit(1);
    }
    console.log(`FFmpeg capability verified: ${manifest.profile_id}, manifest sha256 ${sha256(manifestBytes)}.`);
  } catch (error) {
    console.error(`FFmpeg capability verification failed closed: ${error.message}`);
    process.exit(1);
  }
}
