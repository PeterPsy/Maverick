import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { maverickFrontendAssets } from '../../scripts/vite-frontend-assets.mjs';
import { maverickIsolatedFrameAssetUrls } from '../../scripts/vite-isolated-frame-assets.mjs';

export default defineConfig({
  plugins: [react(), maverickIsolatedFrameAssetUrls(), maverickFrontendAssets()],
  base: '/apps/external-apps/',
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
});
