import {defineConfig} from "vite";
import {maverickFrontendAssets} from "../../scripts/vite-frontend-assets.mjs";
import {maverickIsolatedFrameAssetUrls} from "../../scripts/vite-isolated-frame-assets.mjs";

export default defineConfig({
  plugins:[maverickIsolatedFrameAssetUrls(),maverickFrontendAssets()],
  root:"frontend",base:"/apps/browser/",
  build:{outDir:"dist",emptyOutDir:true,rollupOptions:{output:{entryFileNames:"assets/[name]-[hash].js",assetFileNames:"assets/[name]-[hash][extname]"}}},
});
