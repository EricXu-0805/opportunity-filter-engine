import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'cold-email-confirm.spec.ts',
  grep: /released reminder keeps its saved date/,
  timeout: 70000,
  expect: {timeout: 15000},
  retries: 0,
  workers: 1,
  use: {baseURL: 'https://joinalab.com', serviceWorkers:'block', channel:'chrome'},
});
