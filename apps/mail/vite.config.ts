import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/apps/mail/',
  root: 'frontend',
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
