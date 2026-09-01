import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { maverickFrontendAssets } from '../../scripts/vite-frontend-assets.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react(), maverickFrontendAssets()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'frontend/src')
    }
  },
  root: 'frontend',
  base: '/apps/storage/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'frontend/index.html',
        'widgets/storage-sidebar/index': 'frontend/widgets/storage-sidebar/index.html',
        'widgets/storage-sidebar-footer/index': 'frontend/widgets/storage-sidebar-footer/index.html',
        'widgets/file-preview/index': 'frontend/widgets/file-preview/index.html'
      },
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]'
      }
    }
  }
});
