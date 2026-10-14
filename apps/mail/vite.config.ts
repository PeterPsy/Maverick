import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { loopinoFrontendAssets } from '../../scripts/vite-frontend-assets.mjs';
import { loopinoIsolatedFrameAssetUrls } from '../../scripts/vite-isolated-frame-assets.mjs';

export default defineConfig({
  plugins: [react(), loopinoIsolatedFrameAssetUrls(), loopinoFrontendAssets()],
  base: '/apps/mail/',
  root: 'frontend',
  resolve: { dedupe: ['react', 'react-dom'] },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'frontend/index.html',
        'widgets/mail-sidebar/index': 'frontend/widgets/mail-sidebar/index.html',
        'widgets/mail-sidebar-footer/index': 'frontend/widgets/mail-sidebar-footer/index.html'
      }
    }
  }
});
