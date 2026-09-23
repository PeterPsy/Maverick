import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/apps/marta-ops/',
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
});
