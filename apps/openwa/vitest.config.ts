import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  test: {
    environment: "happy-dom",
    include: ["frontend/tests/**/*.test.tsx"],
    maxWorkers: 1,
    clearMocks: true,
    restoreMocks: true,
  },
});
