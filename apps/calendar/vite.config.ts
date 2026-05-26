import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react(), tailwindcss(), stripGeneratedTrailingWhitespace()],
  root: 'frontend',
  base: '/apps/calendar/',
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
        'widgets/calendar-sidebar/index': 'frontend/widgets/calendar-sidebar/index.html',
        'widgets/calendar-sidebar-footer/index': 'frontend/widgets/calendar-sidebar-footer/index.html'
      },
      output: {
        entryFileNames: 'assets/app-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]'
      }
    }
  }
});

function stripGeneratedTrailingWhitespace(): Plugin {
  return {
    name: 'calendar-strip-generated-trailing-whitespace',
    generateBundle(_options, bundle) {
      Object.values(bundle).forEach((item) => {
        if (item.type === 'chunk') {
          item.code = stripTrailingWhitespace(item.code);
          return;
        }
        if (typeof item.source === 'string') {
          item.source = stripTrailingWhitespace(item.source);
        }
      });
    }
  };
}

function stripTrailingWhitespace(value: string) {
  return value.replace(/[ \t]+$/gm, '');
}
