import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/apps/chat/",
  plugins: [react()],
  root: "frontend",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: "frontend/index.html",
        "widgets/chat-sidebar/index": "frontend/widgets/chat-sidebar/index.html",
      },
    },
  },
});
