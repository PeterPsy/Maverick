import { loopinoFrontendAssets } from "../../scripts/vite-frontend-assets.mjs";
import { loopinoIsolatedFrameAssetUrls } from "../../scripts/vite-isolated-frame-assets.mjs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [
    react(),
    loopinoIsolatedFrameAssetUrls(),
    loopinoFrontendAssets(),
  ],
  base: "/apps/openwa/",
  root: "frontend",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
