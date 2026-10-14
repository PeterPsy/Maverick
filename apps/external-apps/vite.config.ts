import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { loopinoFrontendAssets } from '../../scripts/vite-frontend-assets.mjs';
import { loopinoIsolatedFrameAssetUrls } from '../../scripts/vite-isolated-frame-assets.mjs';

export default defineConfig({
  plugins: [react(), loopinoIsolatedFrameAssetUrls(), loopinoFrontendAssets()],
  base: '/apps/external-apps/',
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: { input: {
      app: fileURLToPath(new URL('./frontend/index.html', import.meta.url)),
      externalSettings: fileURLToPath(new URL('./frontend/widgets/external-surfaces-settings/index.html', import.meta.url)),
    } },
  }
});
