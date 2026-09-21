/** Shared Chromium setup for authenticated disposable browser probes. */
import { existsSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { join } from 'node:path';

if (process.env.MAVERICK_PERFORMANCE_BROWSER_FIXTURE !== '1') throw new Error('Disposable fixture required.');
export const baseUrl = process.argv[2];
if (!/^http:\/\/maverick\.localhost:\d+$/.test(baseUrl)) throw new Error('Local fixture origin required.');
const require = createRequire(new URL('../apps/chat/package.json', import.meta.url));
export const { chromium } = require('playwright');
export function executablePath() {
  const configured = process.env.MAVERICK_PLAYWRIGHT_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (configured && existsSync(configured)) return configured;
  for (const path of ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser']) {
    if (existsSync(path)) return path;
  }
  const cache = join(homedir(), '.cache/ms-playwright');
  if (existsSync(cache)) for (const directory of readdirSync(cache).filter(name => name.startsWith('chromium-')).sort().reverse()) {
    for (const suffix of ['chrome-linux64/chrome', 'chrome-linux/chrome']) {
      const path = join(cache, directory, suffix);
      if (existsSync(path)) return path;
    }
  }
}
