import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

describe('skills modal style', () => {
  it('uses the base background token', () => {
    const styles = readFileSync(resolve(currentDir, 'modal.css'), 'utf8');

    expect(styles).toMatch(/\.loopino-modal\s*\{[^}]*background: var\(--loopino-bg\);/);
    expect(styles).not.toMatch(/\.loopino-modal\s*\{[^}]*background: var\(--loopino-bg-strong\);/);
  });
});
