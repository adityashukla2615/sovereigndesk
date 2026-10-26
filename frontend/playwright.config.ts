/**
 * The Playwright smoke test: the real backend on the committed seed (offline, a throwaway
 * SQLite database) behind the Vite dev server, driven in the installed Chrome. No browser is
 * downloaded: `channel` picks the system's Chrome (SD_BROWSER_CHANNEL=msedge for Edge).
 */

import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { defineConfig } from '@playwright/test';

const root = resolve(import.meta.dirname, '..');
const backendPort = 8078;
const frontendPort = 5178;
const backendUrl = `http://127.0.0.1:${String(backendPort)}`;
const python =
  process.env.SD_PYTHON ?? join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const database = join(tmpdir(), `sovereigndesk-e2e-${String(process.pid)}.db`).replaceAll('\\', '/');

export default defineConfig({
  testDir: 'e2e',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  // One simulator serves every test, and the tests change it: run them one at a time.
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${String(frontendPort)}`,
    channel: process.env.SD_BROWSER_CHANNEL ?? 'chrome',
    viewport: { width: 1680, height: 1050 },
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port ${String(backendPort)}`,
      cwd: join(root, 'backend'),
      url: `${backendUrl}/api/health`,
      env: {
        ...process.env,
        SD_OFFLINE: 'true',
        SD_SCHEDULER_ENABLED: 'false',
        SD_DATABASE_URL: `sqlite:///${database}`,
        SD_DATA_DIR: join(root, 'data'),
        SD_SIM_SEED: '7',
      },
      timeout: 240_000,
      reuseExistingServer: false,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${String(frontendPort)} --strictPort`,
      url: `http://127.0.0.1:${String(frontendPort)}`,
      env: { ...process.env, SD_BACKEND_URL: backendUrl },
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
