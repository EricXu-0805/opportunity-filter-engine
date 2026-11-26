import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  testMatch: 'push-worker-ownership.spec.ts',
  workers: 1,
  retries: 0,
  use: {baseURL:'http://127.0.0.1:3100'},
  webServer: {
    command: 'node e2e/m48-http.mjs',
    url: 'http://127.0.0.1:3100',
    reuseExistingServer: false,
  }
});
