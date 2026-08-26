import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

import { maverickFrontendAssets } from "../../scripts/vite-frontend-assets.mjs";

const appRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  base: "/apps/app-store/",
  root: resolve(appRoot, "frontend/src"),
  plugins: [maverickFrontendAssets()],
  build: {
    outDir: resolve(appRoot, "frontend/dist"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: resolve(appRoot, "frontend/src/index.html"),
        "widgets/app-shortcuts/index": resolve(appRoot, "frontend/src/widgets/app-shortcuts/index.html"),
      },
    },
  },
});
