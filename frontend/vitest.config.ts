import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://localhost:3000',
      },
    },
    globals: true,
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    exclude: ['node_modules/**', 'e2e/**', '.next/**'],
    setupFiles: ['src/test-setup.ts'],
    silent: false,
    onConsoleLog(log, type) {
      if (type === 'stderr' && log.includes('--localstorage-file')) return false;
      return undefined;
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
});
