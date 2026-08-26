import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { posix, relative, resolve, sep } from "node:path";

export const MAVERICK_FRONTEND_ASSET_MANIFEST = "maverick-frontend-assets.json";
export const MAVERICK_FRONTEND_ASSET_SCHEMA = "maverick.frontend-assets.v1";

function sha256(body) {
  return createHash("sha256").update(body).digest("hex");
}

function toPosix(path) {
  return path.split(sep).join(posix.sep);
}

function filesBelow(root) {
  const paths = [];
  function visit(directory) {
    for (const name of readdirSync(directory).sort()) {
      const path = resolve(directory, name);
      const stat = statSync(path);
      if (stat.isDirectory()) {
        visit(path);
      } else if (stat.isFile()) {
        paths.push(toPosix(relative(root, path)));
      }
    }
  }
  visit(root);
  return paths;
}

function recordFor(outDir, path) {
  const body = readFileSync(resolve(outDir, path));
  return { path, sha256: sha256(body), size_bytes: body.byteLength };
}

function canonicalBuildPayload({ entrypoints, immutable, precache = null, revalidated }) {
  const payload = {
    schema: MAVERICK_FRONTEND_ASSET_SCHEMA,
    entrypoints,
    immutable,
    revalidated,
  };
  if (precache !== null) {
    payload.precache = precache;
  }
  return JSON.stringify(payload);
}

function outputUsesContentHash(outputOptions, output) {
  const pattern = output.type === "asset"
    ? outputOptions.assetFileNames
    : output.isEntry
      ? outputOptions.entryFileNames
      : outputOptions.chunkFileNames;
  if (typeof pattern !== "string" || !/\[hash(?::\d+)?\]/.test(pattern)) {
    return false;
  }
  if (output.type === "chunk") {
    return output.preliminaryFileName !== output.fileName;
  }
  return output.originalFileNames.length > 0;
}

function recordsForPaths(outDir, paths, immutableRollupOutputs) {
  const immutable = paths
    .filter((path) => immutableRollupOutputs.has(path))
    .map((path) => recordFor(outDir, path));
  const immutablePaths = new Set(immutable.map(({ path }) => path));
  const revalidated = paths.filter((path) => !immutablePaths.has(path)).map((path) => recordFor(outDir, path));
  return { immutable, revalidated };
}

function precacheRecords({ base, immutable, options, recordsByPath }) {
  if (!options.precache) {
    return [];
  }
  const selected = [];
  for (const route of options.precache.routes || []) {
    selected.push({ url: route.url, path: route.path });
  }
  for (const path of options.precache.paths || []) {
    selected.push({ url: `${base}${path}`.replace(/\/+/g, "/"), path });
  }
  if (options.precache.immutable !== false) {
    for (const { path } of immutable) {
      selected.push({ url: `${base}${path}`.replace(/\/+/g, "/"), path });
    }
  }
  const byUrl = new Map();
  for (const { url, path } of selected) {
    const segments = typeof url === "string" ? url.split("/") : [];
    if (
      typeof url !== "string" ||
      !url.startsWith("/") ||
      !/^\/[A-Za-z0-9._~!$&'()*+,;=:@/-]*$/.test(url) ||
      url.startsWith("//") ||
      url.includes("//") ||
      /[%?#\\\r\n\0]/.test(url) ||
      segments.some((segment) => segment === "." || segment === "..") ||
      url === "/sw.js" ||
      url === "/api" ||
      url.startsWith("/api/") ||
      url === "/ws" ||
      url.startsWith("/ws/") ||
      segments.some((segment) => segment === "backend" || segment === "sidecar")
    ) {
      throw new Error(`Maverick precache URL is unsafe: ${url}`);
    }
    const record = recordsByPath.get(path);
    if (!record) {
      throw new Error(`Maverick precache file is missing: ${path}`);
    }
    if (byUrl.has(url) && byUrl.get(url).path !== path) {
      throw new Error(`Maverick precache URL maps to multiple files: ${url}`);
    }
    byUrl.set(url, { url, path, sha256: record.sha256, size_bytes: record.size_bytes });
  }
  return [...byUrl.values()].sort((left, right) => left.url.localeCompare(right.url));
}

function injectServiceWorker({ buildId, immutable, outDir, precache, serviceWorkerPath }) {
  const path = resolve(outDir, serviceWorkerPath);
  const source = readFileSync(path, "utf8");
  const replacements = {
    __MAVERICK_BUILD_ID__: buildId,
    __MAVERICK_IMMUTABLE_ASSETS__: JSON.stringify(
      immutable.map((record) => ({
        url: record.path,
        sha256: record.sha256,
        size_bytes: record.size_bytes,
      })),
    ),
    __MAVERICK_PRECACHE_MANIFEST__: JSON.stringify(precache),
  };
  let generated = source;
  for (const [token, value] of Object.entries(replacements)) {
    if (!generated.includes(token)) {
      throw new Error(`Maverick service worker token is missing: ${token}`);
    }
    generated = generated.split(token).join(value);
  }
  writeFileSync(path, generated);
}

/**
 * Emit Maverick's verified asset manifest from Rollup's actual output graph.
 *
 * Only Rollup/Vite outputs produced through a naming template containing the
 * real `[hash]` placeholder are classified immutable. Files copied from
 * `publicDir`, explicitly named outputs, HTML entrypoints, workers, and other
 * semantic names remain revalidated even when their filename resembles a hash.
 */
export function maverickFrontendAssets(options = {}) {
  let resolvedConfig;
  const immutableRollupOutputs = new Set();
  return {
    name: "maverick-frontend-assets",
    apply: "build",
    enforce: "post",
    configResolved(config) {
      resolvedConfig = config;
    },
    generateBundle(outputOptions, bundle) {
      for (const [fileName, output] of Object.entries(bundle)) {
        if (
          !fileName.endsWith(".map")
          && !fileName.endsWith(".html")
          && outputUsesContentHash(outputOptions, output)
        ) {
          immutableRollupOutputs.add(fileName);
        }
      }
    },
    closeBundle() {
      const outDir = resolve(resolvedConfig.root, resolvedConfig.build.outDir);
      const paths = filesBelow(outDir).filter(
        (path) => path !== MAVERICK_FRONTEND_ASSET_MANIFEST && !path.endsWith(".map"),
      );
      const entrypoints = paths.filter((path) => path.endsWith(".html"));
      if (entrypoints.length === 0) {
        throw new Error("Maverick frontend builds require at least one HTML entrypoint.");
      }
      let { immutable, revalidated } = recordsForPaths(outDir, paths, immutableRollupOutputs);
      const recordsByPath = new Map([...immutable, ...revalidated].map((record) => [record.path, record]));
      const precache = precacheRecords({
        base: resolvedConfig.base,
        immutable,
        options,
        recordsByPath,
      });
      if (options.offlinePath && !precache.some(({ path }) => path === options.offlinePath)) {
        throw new Error(`Maverick offline shell is not selected for precache: ${options.offlinePath}`);
      }
      // The generated worker embeds buildId, so hashing its final bytes would
      // be circular. Hash its placeholder bytes plus the selected precache
      // records instead. A worker-only change therefore cannot collide with
      // the cache owned by a currently active build.
      const buildId = sha256(canonicalBuildPayload({
        entrypoints,
        immutable,
        precache: options.serviceWorkerPath ? precache : null,
        revalidated,
      }));
      if (options.serviceWorkerPath) {
        injectServiceWorker({
          buildId,
          immutable: immutable.map((record) => ({ ...record, path: `${resolvedConfig.base}${record.path}`.replace(/\/+/g, "/") })),
          outDir,
          precache,
          serviceWorkerPath: options.serviceWorkerPath,
        });
        ({ immutable, revalidated } = recordsForPaths(outDir, paths, immutableRollupOutputs));
      }
      const payload = {
        schema: MAVERICK_FRONTEND_ASSET_SCHEMA,
        build_id: buildId,
        entrypoints,
        immutable,
        revalidated,
      };
      if (precache.length > 0) {
        payload.precache = precache;
      }
      if (options.offlinePath) {
        if (!paths.includes(options.offlinePath)) {
          throw new Error(`Maverick offline shell is missing: ${options.offlinePath}`);
        }
        payload.offline = { path: options.offlinePath };
      }
      writeFileSync(resolve(outDir, MAVERICK_FRONTEND_ASSET_MANIFEST), `${JSON.stringify(payload, null, 2)}\n`);
    },
  };
}
