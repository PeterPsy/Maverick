import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/apps/video-studio/',
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
});
