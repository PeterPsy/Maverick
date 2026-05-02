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
        "widgets/chat-floating/index": "frontend/widgets/chat-floating/index.html",
        "widgets/chat-sidebar-footer/index": "frontend/widgets/chat-sidebar-footer/index.html",
        "widgets/runtime-text/index": "frontend/widgets/runtime-text/index.html",
        "widgets/chat-sidebar/index": "frontend/widgets/chat-sidebar/index.html",
      },
    },
  },
});
