import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { maverickFrontendAssets } from "../../scripts/vite-frontend-assets.mjs";

export default defineConfig({
  base: "/apps/base-shell/",
  plugins: [react(), maverickFrontendAssets()],
  publicDir: "public",
  experimental: {
    renderBuiltUrl(filename) {
      if (filename === "material-symbols-rounded.woff2") {
        return "/material-symbols-rounded.woff2";
      }
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  root: "frontend",
});
