import {defineConfig} from "vite";
import {loopinoFrontendAssets} from "../../scripts/vite-frontend-assets.mjs";
import {loopinoIsolatedFrameAssetUrls} from "../../scripts/vite-isolated-frame-assets.mjs";

export default defineConfig({
  plugins:[loopinoIsolatedFrameAssetUrls(),loopinoFrontendAssets()],
  root:"frontend",base:"/apps/browser/",
  build:{outDir:"dist",emptyOutDir:true,rollupOptions:{output:{entryFileNames:"assets/[name]-[hash].js",assetFileNames:"assets/[name]-[hash][extname]"}}},
});
