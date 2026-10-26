import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Dev server proxies REST and WebSocket traffic to FastAPI, so the app always talks to its own
// origin (`/api`, `/ws`) exactly as it does behind nginx in Docker.
const backend = process.env.SD_BACKEND_URL ?? 'http://127.0.0.1:8000';

// `vite build --mode demo` is the static web demo for GitHub Pages: served under the repository's
// path, with the recorded session (`py tasks.py record-demo`) in place of a backend.
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  base: mode === 'demo' ? (process.env.SD_DEMO_BASE ?? '/sovereigndesk/') : '/',
  publicDir: mode === 'demo' ? 'demo/public' : 'public',
  // The chart chunk (tree-shaken ECharts, loaded lazily after the shell paints) is ~600 kB with
  // TAXCAL's calendar heatmap; the shell itself stays near 400 kB.
  build: { chunkSizeWarningLimit: 650, outDir: mode === 'demo' ? 'dist-demo' : 'dist' },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
  test: {
    // Unit and component tests; e2e/ is Playwright's (`py tasks.py e2e`).
    include: ['src/**/*.test.{ts,tsx}'],
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    unstubGlobals: true,
  },
}));
