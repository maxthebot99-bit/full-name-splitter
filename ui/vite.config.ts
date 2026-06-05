import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

// Build output goes into the Python package so it ships with the wheel.
const OUT_DIR = fileURLToPath(new URL('../src/full_name_splitter/ui_dist', import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        // Stable chunk names so cache-busting isn't churn-on-every-build.
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    // Dev: vite on :5173, FastAPI on :8181. Proxy /api so EventSource works
    // from the same origin without CORS shenanigans during local dev.
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8181',
        changeOrigin: false,
        ws: false,
      },
    },
  },
});
