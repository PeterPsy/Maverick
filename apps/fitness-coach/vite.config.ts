import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { maverickFrontendAssets } from '../../scripts/vite-frontend-assets.mjs';

export default defineConfig({
  plugins: [react(), maverickFrontendAssets()],
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
