import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/apps/platform-connectors/',
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: 'frontend/index.html',
        'widgets/connectors-sidebar/index': 'frontend/widgets/connectors-sidebar/index.html'
      }
    }
  }
});
