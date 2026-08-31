import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { maverickFrontendAssets } from "../../scripts/vite-frontend-assets.mjs";

export default defineConfig({
  base: "/apps/base-shell/",
  plugins: [
    react(),
    maverickFrontendAssets({
      serviceWorkerPath: "sw.js",
      precache: {
        immutable: true,
        routes: [
          { url: "/", path: "index.html" },
          { url: "/favicon.ico", path: "favicon.ico" },
          { url: "/manifest.webmanifest", path: "manifest.webmanifest" },
          { url: "/material-symbols-rounded.woff2", path: "material-symbols-rounded.woff2" },
        ],
        paths: [
          "app-icon-lightcolor.png",
          "maverick-logotype.svg",
          "maverick-mark.svg",
          "pwa-apple-touch-icon.png",
          "pwa-logo-192.png",
          "pwa-logo.png",
          "pwa-maskable-logo.png",
          "sidebar-logo-black.svg",
          "sidebar-logo.svg",
        ],
      },
    }),
  ],
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
    rollupOptions: {
      input: { index: "frontend/index.html" },
    },
  },
  root: "frontend",
});
