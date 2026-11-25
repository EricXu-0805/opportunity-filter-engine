import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', timeout: 60000, retries: 0, workers: 1, reporter: 'list',
  globalSetup: './e2e/global-setup.ts',
  use: { baseURL: 'http://127.0.0.1:3100', storageState: './e2e/.storage-state.json' },
  webServer: [
    { command: 'node e2e/supabase-stub.mjs', url: 'http://127.0.0.1:54321/health' },
    { command: 'node node_modules/next/dist/bin/next dev --webpack --hostname 127.0.0.1 --port 3100',
      url: 'http://127.0.0.1:3100/dashboard', timeout: 120000,
      env: { NEXT_PUBLIC_SUPABASE_URL:'http://127.0.0.1:54321',NEXT_PUBLIC_SUPABASE_ANON_KEY:'e2e-loopback-stub-anon-key-not-a-real-key',BACKEND_URL:'http://127.0.0.1:8100',NEXT_TELEMETRY_DISABLED:'1' } },
  ],
});
