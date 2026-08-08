#!/usr/bin/env node

import {createHash} from "node:crypto";
import {mkdir, mkdtemp, readFile, readdir, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";
import {
  APP_ROOT,
  lockComponents,
  readJson,
  sha256,
} from "./supply-chain-lib.mjs";

function verifyIntegrity(buffer, integrity) {
  const [algorithm, expected] = integrity.split("-", 2);
  if (algorithm !== "sha512" || !expected) {
    throw new Error(`unsupported npm integrity ${integrity}`);
  }
  const observed = createHash(algorithm).update(buffer).digest("base64");
  if (observed !== expected) {
    throw new Error("downloaded tarball does not match package-lock integrity");
  }
}

function run(command, argv, options = {}) {
  const result = spawnSync(command, argv, {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    shell: false,
    ...options,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`${command} ${argv.join(" ")} failed: ${result.error?.message ?? result.stderr}`);
  }
  return result.stdout;
}

function validateTarEntries(output) {
  for (const entry of output.split("\n").filter(Boolean)) {
    const normalized = path.posix.normalize(entry);
    if (path.posix.isAbsolute(entry) || normalized === ".." || normalized.startsWith("../")) {
      throw new Error(`unsafe tar entry ${entry}`);
    }
  }
}

function isEmbeddedNativeFile(name) {
  return /^(?:ffmpeg|ffprobe|remotion)(?:\.exe)?$/.test(name) || /\.(?:so|dylib|dll)$/.test(name);
}

function buildFlags(output) {
  return output
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("--"));
}

const policy = await readJson(path.join(APP_ROOT, "compliance/supply-chain-policy.json"));
const lockfile = await readJson(path.join(APP_ROOT, "package-lock.json"));
const components = lockComponents(lockfile);
const workRoot = await mkdtemp(path.join(tmpdir(), "video-studio-compositor-inventory-"));
const packages = [];

try {
  for (const packageName of policy.remotion.compositor_packages) {
    const component = components.find((item) => item.name === packageName);
    if (!component?.resolved || !component?.integrity) {
      throw new Error(`${packageName} is missing resolved URL or integrity in the lockfile`);
    }

    const response = await fetch(component.resolved, {redirect: "error"});
    if (!response.ok) {
      throw new Error(`${packageName} download failed with HTTP ${response.status}`);
    }
    const archive = Buffer.from(await response.arrayBuffer());
    verifyIntegrity(archive, component.integrity);

    const packageSlug = packageName.replaceAll("/", "-").replaceAll("@", "");
    const archivePath = path.join(workRoot, `${packageSlug}.tgz`);
    const extractRoot = path.join(workRoot, packageSlug);
    await writeFile(archivePath, archive);
    const entries = run("tar", ["-tzf", archivePath]);
    validateTarEntries(entries);
    await mkdir(extractRoot);
    run("tar", ["-xzf", archivePath, "-C", extractRoot]);

    const unpackedRoot = path.join(extractRoot, "package");
    const packageMetadata = JSON.parse(await readFile(path.join(unpackedRoot, "package.json"), "utf8"));
    const embeddedFiles = [];
    for (const entry of await readdir(unpackedRoot, {withFileTypes: true})) {
      if (!entry.isFile() || !isEmbeddedNativeFile(entry.name)) {
        continue;
      }
      const content = await readFile(path.join(unpackedRoot, entry.name));
      embeddedFiles.push({path: entry.name, bytes: content.length, sha256: sha256(content)});
    }
    embeddedFiles.sort((left, right) => left.path.localeCompare(right.path));

    let embeddedFfmpegObservation = null;
    if (packageName === "@remotion/compositor-linux-x64-gnu") {
      const executable = path.join(unpackedRoot, "ffmpeg");
      const versionOutput = run(executable, ["-version"], {env: {LANG: "C", LC_ALL: "C"}});
      const buildOutput = run(executable, ["-buildconf"], {env: {LANG: "C", LC_ALL: "C"}});
      embeddedFfmpegObservation = {
        version_first_line: versionOutput.split("\n")[0],
        build_flags: buildFlags(buildOutput),
        legal_risk_flags: buildFlags(buildOutput).filter((flag) =>
          ["--enable-gpl", "--enable-libfdk-aac", "--enable-libx264", "--enable-libx265"].includes(flag),
        ),
      };
    }

    packages.push({
      name: packageName,
      version: component.version,
      npm_resolved: component.resolved,
      npm_integrity: component.integrity,
      archive_bytes: archive.length,
      archive_sha256: sha256(archive),
      platform: {
        os: packageMetadata.os ?? [],
        cpu: packageMetadata.cpu ?? [],
        libc: packageMetadata.libc ?? [],
      },
      license_metadata: packageMetadata.license ?? "NOASSERTION",
      license_files_in_tarball: entries
        .split("\n")
        .filter((entry) => /(?:^|\/)(?:licen[cs]e|copying)(?:\.|$)/i.test(entry)),
      embedded_files: embeddedFiles,
      embedded_ffmpeg_observation: embeddedFfmpegObservation,
      redistribution_allowed: false,
    });
  }

  const inventory = {
    schema_version: 1,
    snapshot_date: policy.snapshot_date,
    source: "npm registry tarballs resolved and integrity-pinned by package-lock.json",
    status: "development inventory only; not a release redistribution approval",
    risk: "All compositor tarballs omit adequate license metadata while embedding FFmpeg/ffprobe and native libraries. The executable build inspected for linux-x64-gnu is GPL-enabled and includes libfdk-aac, libx264, and libx265.",
    packages,
  };
  await writeFile(
    path.join(APP_ROOT, "compliance/remotion-compositor-inventory.json"),
    `${JSON.stringify(inventory, null, 2)}\n`,
  );
  console.log(`Inventoried ${packages.length} Remotion compositor tarballs.`);
} finally {
  await rm(workRoot, {recursive: true, force: true});
}
