import { maverickFrontendAssets } from "../../../../scripts/vite-frontend-assets.mjs";
import { maverickIsolatedFrameAssetUrls } from "../../../../scripts/vite-isolated-frame-assets.mjs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [
    react(),
    maverickIsolatedFrameAssetUrls(),
    maverickFrontendAssets(),
  ],
  base: "/apps/openwa/",
  root: "frontend",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
