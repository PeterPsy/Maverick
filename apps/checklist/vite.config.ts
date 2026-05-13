import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  root: 'frontend',
  base: '/apps/checklist/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./frontend/src', import.meta.url))
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'frontend/index.html',
        'widgets/checklist-sidebar/index': 'frontend/widgets/checklist-sidebar/index.html',
        'widgets/checklist-sidebar-footer/index': 'frontend/widgets/checklist-sidebar-footer/index.html',
        'widgets/design-checklist/index': 'frontend/widgets/design-checklist/index.html'
      },
      output: {
        entryFileNames: 'assets/app-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]'
      }
    }
  }
});
