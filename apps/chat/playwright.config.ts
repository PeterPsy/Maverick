import { defineConfig, devices } from "@playwright/test";
import { existsSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const PORT = Number(process.env.CHAT_PLAYWRIGHT_PORT || 5188);
const chromiumExecutablePath = discoverChromiumExecutablePath();

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  outputDir: "./test-results",
  reporter: process.env.CI ? "dot" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "on-first-retry",
  },
  webServer: {
    command: `VITE_MAVERICK_FEATURE_GROUP_CHAT=1 npm run dev -- --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/apps/chat/`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: chromiumExecutablePath ? { executablePath: chromiumExecutablePath } : undefined,
      },
    },
  ],
});

function discoverChromiumExecutablePath(): string | undefined {
  const explicit = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (explicit) {
    return explicit;
  }

  const browserRoots = uniqueStrings([
    process.env.PLAYWRIGHT_BROWSERS_PATH,
    join(homedir(), ".cache", "ms-playwright"),
    "/home/ubuntu/.cache/ms-playwright",
  ]);
  const executableRels = [
    "chrome-headless-shell-linux64/chrome-headless-shell",
    "chrome-linux64/chrome",
  ];

  for (const root of browserRoots) {
    if (!root || !existsSync(root)) {
      continue;
    }
    const browserDirs = readdirSync(root)
      .filter((entry) => entry.startsWith("chromium"))
      .sort((left, right) => right.localeCompare(left, undefined, { numeric: true }));
    for (const browserDir of browserDirs) {
      for (const executableRel of executableRels) {
        const candidate = join(root, browserDir, executableRel);
        if (existsSync(candidate)) {
          return candidate;
        }
      }
    }
  }
  return undefined;
}

function uniqueStrings(values: Array<string | undefined>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value))));
}
