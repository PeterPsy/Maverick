import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: { include: ['frontend/src/**/*.test.{ts,tsx}'], maxWorkers: 1 },
});
