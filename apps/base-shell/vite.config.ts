import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/apps/base-shell/",
  plugins: [react()],
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
