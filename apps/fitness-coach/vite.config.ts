import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { loopinoFrontendAssets } from '../../scripts/vite-frontend-assets.mjs';
import { loopinoIsolatedFrameAssetUrls } from '../../scripts/vite-isolated-frame-assets.mjs';

export default defineConfig({
  plugins: [react(), loopinoIsolatedFrameAssetUrls(), loopinoFrontendAssets()],
  base: '/apps/fitness-coach/',
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'frontend/index.html',
        'widgets/fitness-coach-sidebar/index': 'frontend/widgets/fitness-coach-sidebar/index.html',
        'widgets/fitness-coach-sidebar-footer/index': 'frontend/widgets/fitness-coach-sidebar-footer/index.html'
      }
    }
  }
});
