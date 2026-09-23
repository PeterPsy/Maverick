import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/apps/marta-ops/',
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'frontend/index.html',
        'widgets/marta-ops-sidebar/index': 'frontend/widgets/marta-ops-sidebar/index.html',
        'widgets/marta-ops-sidebar-footer/index': 'frontend/widgets/marta-ops-sidebar-footer/index.html'
      },
      output: {
        entryFileNames: 'assets/app-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]'
      }
    }
  }
});
