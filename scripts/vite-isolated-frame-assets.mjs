const APP_BASE_PATTERN = /^\/apps\/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\/$/;

/**
 * Keep Vite's HTML/CSS URLs on the public app mount while making URLs emitted
 * from JavaScript relative to the module that owns them.
 *
 * Core rewrites the generated HTML references to the platform origin before an
 * isolated document runs. The owning module therefore also executes from the
 * platform origin, and Vite's `{ relative: true }` form resolves lazy preload,
 * worker, and imported-media URLs against that public module URL instead of the
 * isolated document origin.
 */
export function maverickIsolatedFrameAssetUrls() {
  return {
    name: "maverick-isolated-frame-asset-urls",
    apply: "build",
    config(config) {
      const base = exactAppBase(config.base);
      return {
        experimental: {
          renderBuiltUrl(filename, { hostType }) {
            safeBuiltFilename(filename);
            return hostType === "js"
              ? { relative: true }
              : `${base}${filename}`;
          },
        },
      };
    },
  };
}

function exactAppBase(value) {
  if (typeof value !== "string" || !APP_BASE_PATTERN.test(value)) {
    throw new Error("Isolated Maverick frontends require one exact /apps/<app_id>/ Vite base.");
  }
  return value;
}

function safeBuiltFilename(value) {
  if (
    typeof value !== "string"
    || !value
    || value.startsWith("/")
    || value.includes("\\")
    || /[?#\u0000-\u001f\u007f]/u.test(value)
    || value.split("/").some((segment) => segment === "." || segment === "..")
  ) {
    throw new Error(`Vite emitted an unsafe Maverick frontend asset path: ${value}`);
  }
}
