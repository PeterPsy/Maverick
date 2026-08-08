#!/usr/bin/env node

import {lstat, mkdtemp, readdir, readFile, readlink, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {APP_ROOT, readJson, sha256} from "./supply-chain-lib.mjs";

const COMPOSITOR_PATTERN = /(?:^|\/)@remotion\/compositor-[^/]+(?:\/|$)/;
const MEDIA_BINARY_PATTERN = /(?:^|\/)(?:ffmpeg|ffprobe)(?:\.exe)?$/i;
const ARCHIVE_PATTERN = /\.(?:tar|tgz|tar\.gz|zip)$/i;

function run(command, argv) {
  const result = spawnSync(command, argv, {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    shell: false,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`${command} could not inspect artifact: ${result.error?.message ?? result.stderr}`);
  }
  return result.stdout;
}

export function validateArchiveEntries(entries) {
  if (entries.length > 100_000) {
    throw new Error("archive has more than 100000 entries");
  }
  for (const entry of entries) {
    const normalized = path.posix.normalize(entry);
    if (path.posix.isAbsolute(entry) || normalized === ".." || normalized.startsWith("../")) {
      throw new Error(`archive contains unsafe path ${entry}`);
    }
  }
}

async function extractArchive(archivePath, extractRoot) {
  const isZip = archivePath.toLowerCase().endsWith(".zip");
  const listCommand = isZip ? ["unzip", ["-Z1", archivePath]] : ["tar", ["-tf", archivePath]];
  const entries = run(...listCommand).split("\n").filter(Boolean);
  validateArchiveEntries(entries);
  if (isZip) {
    run("unzip", ["-qq", archivePath, "-d", extractRoot]);
  } else {
    run("tar", ["-xf", archivePath, "-C", extractRoot]);
  }
}

function normalizedRelative(root, target) {
  return path.relative(root, target).split(path.sep).join("/");
}

export async function scanReleaseArtifact(artifactPath, {maxArchiveDepth = 4} = {}) {
  const root = path.resolve(artifactPath);
  const [inventory, hostManifest] = await Promise.all([
    readJson(path.join(APP_ROOT, "compliance/remotion-compositor-inventory.json")),
    readJson(path.join(APP_ROOT, "compliance/ffmpeg-host-manifest.json")),
  ]);
  const blockedDigests = new Set([
    ...inventory.packages.flatMap((item) => [
      item.archive_sha256,
      ...item.embedded_files.map((file) => file.sha256),
    ]),
    hostManifest.binaries.ffmpeg.sha256,
    hostManifest.binaries.ffprobe.sha256,
  ]);
  const findings = [];
  let visited = 0;

  async function scan(target, displayRoot, archiveDepth) {
    visited += 1;
    if (visited > 100_000) {
      throw new Error("artifact contains more than 100000 filesystem entries");
    }
    const metadata = await lstat(target);
    const relative = normalizedRelative(displayRoot, target) || path.basename(target);
    const normalized = relative.replace(/^\.\//, "");

    if (COMPOSITOR_PATTERN.test(normalized)) {
      findings.push({kind: "remotion-compositor", path: normalized});
    }
    if (MEDIA_BINARY_PATTERN.test(normalized)) {
      findings.push({kind: "embedded-media-binary", path: normalized});
    }
    if (metadata.isSymbolicLink()) {
      const destination = await readlink(target);
      if (MEDIA_BINARY_PATTERN.test(destination.split(path.sep).join("/"))) {
        findings.push({kind: "embedded-media-binary-symlink", path: normalized});
      }
      return;
    }
    if (metadata.isDirectory()) {
      for (const entry of await readdir(target)) {
        await scan(path.join(target, entry), displayRoot, archiveDepth);
      }
      return;
    }
    if (!metadata.isFile()) {
      return;
    }
    const digest = sha256(await readFile(target));
    if (blockedDigests.has(digest)) {
      findings.push({kind: "known-blocked-payload", path: normalized, sha256: digest});
    }
    if (!ARCHIVE_PATTERN.test(target)) return;
    if (archiveDepth >= maxArchiveDepth) {
      throw new Error(`nested archive depth exceeds ${maxArchiveDepth} at ${normalized}`);
    }
    const extractRoot = await mkdtemp(path.join(tmpdir(), "video-studio-release-gate-"));
    try {
      await extractArchive(target, extractRoot);
      await scan(extractRoot, extractRoot, archiveDepth + 1);
    } finally {
      await rm(extractRoot, {recursive: true, force: true});
    }
  }

  await scan(root, root, 0);
  return findings;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const artifactPath = process.argv[2];
  if (!artifactPath) {
    console.error("Usage: node scripts/compliance/verify-release-artifact.mjs <release|bundle|container path>");
    process.exit(2);
  }
  try {
    const findings = await scanReleaseArtifact(artifactPath);
    if (findings.length > 0) {
      console.error("Release artifact blocked by unresolved redistribution policy:");
      for (const finding of findings) {
        console.error(`- ${finding.kind}: ${finding.path}`);
      }
      process.exit(1);
    }
    console.log("Release artifact contains no embedded Remotion compositor, FFmpeg, or ffprobe payload.");
  } catch (error) {
    console.error(`Release artifact inspection failed closed: ${error.message}`);
    process.exit(1);
  }
}
