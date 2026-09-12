import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { maverickFrontendAssets } from '../../../../scripts/vite-frontend-assets.mjs';
import { maverickIsolatedFrameAssetUrls } from '../../../../scripts/vite-isolated-frame-assets.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react(), maverickIsolatedFrameAssetUrls(), maverickFrontendAssets()],
  resolve: { alias: { '@': path.resolve(__dirname, 'frontend/src') } },
  root: 'frontend',
  base: '/apps/videomaker-selection/',
  build: {
    outDir: 'dist', emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'frontend/index.html',
        'widgets/videomaker-sidebar/index': 'frontend/widgets/videomaker-sidebar/index.html',
        'widgets/videomaker-sidebar-footer/index': 'frontend/widgets/videomaker-sidebar-footer/index.html'
      },
      output: { entryFileNames: 'assets/[name]-[hash].js', chunkFileNames: 'assets/[name]-[hash].js', assetFileNames: 'assets/[name]-[hash][extname]' }
    }
  }
});
