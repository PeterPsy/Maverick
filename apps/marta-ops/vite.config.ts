import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { maverickFrontendAssets } from "../../../../scripts/vite-frontend-assets.mjs";
import { maverickIsolatedFrameAssetUrls } from "../../../../scripts/vite-isolated-frame-assets.mjs";

export default defineConfig({
  plugins: [
    react(),
    maverickIsolatedFrameAssetUrls(),
    maverickFrontendAssets(),
  ],
  base: "/apps/marta-ops/",
  root: "frontend",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: "frontend/index.html",
        "widgets/marta-ops-sidebar/index":
          "frontend/widgets/marta-ops-sidebar/index.html",
        "widgets/marta-ops-sidebar-footer/index":
          "frontend/widgets/marta-ops-sidebar-footer/index.html",
      },
      output: {
        entryFileNames: "assets/app-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
