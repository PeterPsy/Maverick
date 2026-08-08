import {createHash} from "node:crypto";
import {readFile, readdir, realpath, stat} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {inspectModelInventory} from "./model-policy.mjs";

export const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

export function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

export async function sha256File(filePath) {
  return sha256(await readFile(filePath));
}

export function packageNameFromLockPath(lockPath) {
  const marker = "node_modules/";
  const index = lockPath.lastIndexOf(marker);
  if (index < 0) {
    return null;
  }
  const remainder = lockPath.slice(index + marker.length);
  const parts = remainder.split("/");
  return parts[0].startsWith("@") ? parts.slice(0, 2).join("/") : parts[0];
}

export function lockComponents(lockfile) {
  return Object.entries(lockfile.packages ?? {})
    .filter(([lockPath]) => lockPath.includes("node_modules/"))
    .map(([lockPath, metadata]) => ({
      lockPath,
      name: packageNameFromLockPath(lockPath),
      ...metadata,
    }))
    .sort((left, right) => left.lockPath.localeCompare(right.lockPath));
}

function isExactVersion(value) {
  return /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(value ?? "");
}

function isRemotionPackage(name) {
  return name === "remotion" || name?.startsWith("@remotion/");
}

function licenseDiagnostic(component, policy) {
  const license = component.license;
  const allowed = new Set(policy.licenses.allowed_spdx_expressions);
  if (license && allowed.has(license)) {
    return null;
  }

  const remotionLabels = new Set(policy.licenses.remotion_license_labels);
  if (
    isRemotionPackage(component.name) &&
    component.version === policy.remotion.approved_version &&
    remotionLabels.has(license)
  ) {
    return null;
  }

  const exception = policy.licenses.development_only_exceptions.find(
    (candidate) =>
      component.name?.startsWith(candidate.package_prefix) &&
      policy.remotion.compositor_packages.includes(component.name) &&
      component.version === candidate.version &&
      candidate.redistribution_allowed === false,
  );
  if (!license && exception) {
    return null;
  }

  if (!license) {
    return `${component.name}@${component.version} has UNKNOWN/absent license metadata and no governed exception`;
  }
  const upper = license.toUpperCase();
  const token = policy.licenses.blocked_tokens.find((candidate) => upper.includes(candidate));
  if (token) {
    return `${component.name}@${component.version} uses blocked ${token} license metadata \`${license}\` without a governed exception`;
  }
  return `${component.name}@${component.version} uses unapproved license metadata \`${license}\``;
}

export function inspectSupplyChain({packageManifest, lockfile, policy, compositorInventory, modelInventory}) {
  const errors = [];
  const dependencies = packageManifest.dependencies ?? {};
  const rootLock = lockfile.packages?.[""] ?? {};

  if (packageManifest.packageManager !== policy.node.package_manager) {
    errors.push(`packageManager must be exactly ${policy.node.package_manager}`);
  }
  if (packageManifest.engines?.node !== policy.node.range) {
    errors.push(`Node engine must be exactly ${policy.node.range}`);
  }
  if (lockfile.lockfileVersion !== policy.node.lockfile_version) {
    errors.push(`lockfileVersion must be ${policy.node.lockfile_version}`);
  }

  for (const packageName of policy.remotion.direct_packages) {
    const declared = dependencies[packageName];
    if (!declared) {
      errors.push(`required direct dependency ${packageName} is missing`);
    } else if (!isExactVersion(declared) || declared !== policy.remotion.approved_version) {
      errors.push(`${packageName} must use exact version ${policy.remotion.approved_version}; found ${declared}`);
    }
    if (rootLock.dependencies?.[packageName] !== declared) {
      errors.push(`lockfile root dependency for ${packageName} does not match package.json`);
    }
  }

  const components = lockComponents(lockfile);
  const forbidden = new Set(policy.remotion.forbidden_packages);
  const remotionComponents = components.filter((component) => isRemotionPackage(component.name));
  const approvedRemotionNames = [...policy.remotion.approved_locked_packages].sort();
  const observedRemotionNames = [...new Set(remotionComponents.map((component) => component.name))].sort();
  if (JSON.stringify(observedRemotionNames) !== JSON.stringify(approvedRemotionNames)) {
    errors.push("locked Remotion package set differs from the reviewed policy inventory");
  }
  for (const component of components) {
    if (!component.resolved?.startsWith("https://registry.npmjs.org/")) {
      errors.push(`${component.name}@${component.version} is not resolved from the reviewed npm registry`);
    }
    if (!component.integrity?.startsWith("sha512-")) {
      errors.push(`${component.name}@${component.version} lacks sha512 lockfile integrity`);
    }
  }
  for (const component of remotionComponents) {
    if (forbidden.has(component.name)) {
      errors.push(`forbidden package ${component.name} is present in the lockfile`);
    }
    if (component.version !== policy.remotion.approved_version) {
      errors.push(`${component.name} is misaligned at ${component.version}; expected ${policy.remotion.approved_version}`);
    }
  }

  for (const forbiddenName of forbidden) {
    if (Object.hasOwn(dependencies, forbiddenName) || Object.hasOwn(packageManifest.devDependencies ?? {}, forbiddenName)) {
      errors.push(`forbidden package ${forbiddenName} is declared directly`);
    }
  }

  const renderer = components.find((component) => component.name === "@remotion/renderer");
  const expectedCompositors = [...policy.remotion.compositor_packages].sort();
  const declaredCompositors = Object.keys(renderer?.optionalDependencies ?? {}).sort();
  if (JSON.stringify(declaredCompositors) !== JSON.stringify(expectedCompositors)) {
    errors.push("@remotion/renderer optional compositor set differs from the reviewed inventory");
  }
  for (const packageName of expectedCompositors) {
    if (renderer?.optionalDependencies?.[packageName] !== policy.remotion.approved_version) {
      errors.push(`${packageName} optional dependency is not exact-aligned`);
    }
  }

  for (const component of components) {
    const diagnostic = licenseDiagnostic(component, policy);
    if (diagnostic) {
      errors.push(diagnostic);
    }
  }

  if (compositorInventory) {
    const inventoryNames = compositorInventory.packages?.map((item) => item.name).sort() ?? [];
    if (JSON.stringify(inventoryNames) !== JSON.stringify(expectedCompositors)) {
      errors.push("committed compositor inventory does not cover the exact optional dependency set");
    }
    for (const item of compositorInventory.packages ?? []) {
      const locked = components.find((component) => component.name === item.name);
      if (!locked || locked.version !== item.version || locked.integrity !== item.npm_integrity) {
        errors.push(`${item.name} inventory provenance differs from the lockfile`);
      }
      if (!/^[a-f0-9]{64}$/.test(item.archive_sha256 ?? "") || !item.embedded_files?.some((file) => /(^|\/)ffmpeg(?:\.exe)?$/.test(file.path))) {
        errors.push(`${item.name} inventory is missing archive or embedded FFmpeg evidence`);
      }
      for (const file of item.embedded_files ?? []) {
        if (!/^[a-f0-9]{64}$/.test(file.sha256 ?? "") || !Number.isSafeInteger(file.bytes) || file.bytes <= 0) {
          errors.push(`${item.name} has invalid embedded-file provenance for ${file.path ?? "<unknown>"}`);
        }
      }
      if (item.license_metadata !== "NOASSERTION" || item.redistribution_allowed !== false) {
        errors.push(`${item.name} must remain explicitly unlicensed for release redistribution`);
      }
    }
  }

  errors.push(...inspectModelInventory(modelInventory, policy.models));

  return {components, errors};
}

export async function loadSupplyChainInputs(root = APP_ROOT) {
  const [packageManifest, lockfile, policy, compositorInventory, modelInventory] = await Promise.all([
    readJson(path.join(root, "package.json")),
    readJson(path.join(root, "package-lock.json")),
    readJson(path.join(root, "compliance/supply-chain-policy.json")),
    readJson(path.join(root, "compliance/remotion-compositor-inventory.json")),
    readJson(path.join(root, "compliance/model-inventory.json")),
  ]);
  return {packageManifest, lockfile, policy, compositorInventory, modelInventory};
}

export async function assertLicenseFiles(root, policy) {
  const packages = ["remotion", "@remotion/player", "@remotion/renderer", "@remotion/bundler"];
  const errors = [];
  for (const packageName of packages) {
    const packageRoot = path.join(root, "node_modules", ...packageName.split("/"));
    try {
      const resolved = await realpath(path.join(packageRoot, "LICENSE.md"));
      const digest = await sha256File(resolved);
      if (digest !== policy.remotion.license_file_sha256) {
        errors.push(`${packageName} license checksum changed: ${digest}`);
      }
    } catch (error) {
      errors.push(`${packageName} license file is unavailable: ${error.code ?? error.message}`);
    }
  }
  return errors;
}

export async function assertInstalledCompositors(root, inventory) {
  const errors = [];
  for (const item of inventory.packages ?? []) {
    const packageRoot = path.join(root, "node_modules", ...item.name.split("/"));
    try {
      await stat(packageRoot);
    } catch (error) {
      if (error.code === "ENOENT") continue;
      errors.push(`${item.name} installed compositor root verification failed: ${error.message}`);
      continue;
    }
    try {
      const packageMetadata = await readJson(path.join(packageRoot, "package.json"));
      if (packageMetadata.version !== item.version) {
        errors.push(`${item.name} installed version differs from compositor inventory`);
      }
      if (packageMetadata.license !== undefined) {
        errors.push(`${item.name} installed license metadata changed and requires review`);
      }
      const observedFiles = [];
      for (const expected of item.embedded_files) {
        const filePath = path.join(packageRoot, expected.path);
        const [digest, metadata] = await Promise.all([sha256File(filePath), stat(filePath)]);
        observedFiles.push(expected.path);
        if (digest !== expected.sha256 || metadata.size !== expected.bytes) {
          errors.push(`${item.name}/${expected.path} differs from the reviewed embedded-file inventory`);
        }
      }
      const rootFiles = (await readdir(packageRoot, {withFileTypes: true}))
        .filter(
          (entry) =>
            entry.isFile() &&
            (/^(?:ffmpeg|ffprobe|remotion)(?:\.exe)?$/.test(entry.name) || /\.(?:so|dylib|dll)$/.test(entry.name)),
        )
        .map((entry) => entry.name)
        .sort();
      if (JSON.stringify(rootFiles) !== JSON.stringify(observedFiles.sort())) {
        errors.push(`${item.name} installed embedded-file set differs from the reviewed inventory`);
      }
    } catch (error) {
      errors.push(`${item.name} installed compositor verification failed: ${error.message}`);
    }
  }
  return errors;
}

export function npmPurl(name, version) {
  const encodedName = name.startsWith("@")
    ? `%40${encodeURIComponent(name.slice(1).split("/")[0])}/${encodeURIComponent(name.split("/")[1])}`
    : encodeURIComponent(name);
  return `pkg:npm/${encodedName}@${encodeURIComponent(version)}`;
}

export function integrityHash(integrity) {
  if (!integrity?.startsWith("sha512-")) {
    return null;
  }
  return Buffer.from(integrity.slice("sha512-".length), "base64").toString("hex").toUpperCase();
}
