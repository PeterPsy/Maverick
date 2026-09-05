import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { maverickFrontendAssets } from '../../scripts/vite-frontend-assets.mjs';
import { maverickIsolatedFrameAssetUrls } from '../../scripts/vite-isolated-frame-assets.mjs';

export default defineConfig({
  plugins: [react(), maverickIsolatedFrameAssetUrls(), maverickFrontendAssets()],
  base: '/apps/crm/',
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'frontend/index.html',
        'widgets/crm-sidebar/index': 'frontend/widgets/crm-sidebar/index.html'
      },
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]'
      }
    }
  }
});
