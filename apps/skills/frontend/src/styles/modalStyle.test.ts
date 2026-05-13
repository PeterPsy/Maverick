import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

describe('skills modal style', () => {
  it('uses the base background token', () => {
    const styles = readFileSync(resolve(currentDir, 'modal.css'), 'utf8');

    expect(styles).toMatch(/\.maverick-modal\s*\{[^}]*background: var\(--maverick-bg\);/);
    expect(styles).not.toMatch(/\.maverick-modal\s*\{[^}]*background: var\(--maverick-bg-strong\);/);
  });
});
