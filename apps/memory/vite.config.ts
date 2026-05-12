import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/apps/memory/",
  plugins: [react()],
  root: "frontend",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: "frontend/index.html",
        "widgets/memory-sidebar/index": "frontend/widgets/memory-sidebar/index.html",
        "widgets/memory-sidebar-footer/index": "frontend/widgets/memory-sidebar-footer/index.html",
      },
      output: {
        entryFileNames: "assets/app-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
