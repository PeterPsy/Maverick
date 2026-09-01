import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { maverickFrontendAssets } from "../../scripts/vite-frontend-assets.mjs";
import { maverickIsolatedFrameAssetUrls } from "../../scripts/vite-isolated-frame-assets.mjs";

export default defineConfig({
  base: "/apps/chat/",
  plugins: [react(), maverickIsolatedFrameAssetUrls(), maverickFrontendAssets()],
  root: "frontend",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: "frontend/index.html",
        "widgets/chat-floating-dock/index": "frontend/widgets/chat-floating-dock/index.html",
        "widgets/chat-floating/index": "frontend/widgets/chat-floating/index.html",
        "widgets/chat-sidebar-footer/index": "frontend/widgets/chat-sidebar-footer/index.html",
        "widgets/runtime-text/index": "frontend/widgets/runtime-text/index.html",
        "widgets/chat-sidebar/index": "frontend/widgets/chat-sidebar/index.html",
      },
    },
  },
});
