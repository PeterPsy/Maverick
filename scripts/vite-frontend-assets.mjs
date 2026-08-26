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

function canonicalBuildPayload({ entrypoints, immutable, revalidated }) {
  return JSON.stringify({
    schema: MAVERICK_FRONTEND_ASSET_SCHEMA,
    entrypoints,
    immutable,
    revalidated,
  });
}

function hasGeneratedHash(path) {
  return /(?:^|\/)[^/]+-[A-Za-z0-9_-]{8,}\.[^/]+$/.test(path);
}

/**
 * Emit Maverick's verified asset manifest from Rollup's actual output graph.
 *
 * Rollup/Vite outputs are the only files classified immutable. Files copied
 * from `publicDir`, HTML entrypoints, workers, and other semantic names remain
 * revalidated even when their filename happens to resemble a hash.
 */
export function maverickFrontendAssets(options = {}) {
  let resolvedConfig;
  const rollupOutputs = new Set();
  return {
    name: "maverick-frontend-assets",
    apply: "build",
    enforce: "post",
    configResolved(config) {
      resolvedConfig = config;
    },
    generateBundle(_outputOptions, bundle) {
      for (const [fileName, output] of Object.entries(bundle)) {
        if (output.type === "chunk" || (output.type === "asset" && !fileName.endsWith(".html"))) {
          if (!fileName.endsWith(".map")) {
            rollupOutputs.add(fileName);
          }
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
      const immutable = paths
        .filter((path) => rollupOutputs.has(path) && hasGeneratedHash(path))
        .map((path) => recordFor(outDir, path));
      const immutablePaths = new Set(immutable.map(({ path }) => path));
      const revalidated = paths.filter((path) => !immutablePaths.has(path)).map((path) => recordFor(outDir, path));
      const buildId = sha256(canonicalBuildPayload({ entrypoints, immutable, revalidated }));
      const payload = {
        schema: MAVERICK_FRONTEND_ASSET_SCHEMA,
        build_id: buildId,
        entrypoints,
        immutable,
        revalidated,
      };
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
