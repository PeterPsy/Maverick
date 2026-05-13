import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string) {
  return readFileSync(resolve(currentDir, filename), 'utf8');
}

describe('mobile agents safe area layout', () => {
  it('fades mobile content under installed web app chrome', () => {
    const baseStyles = readStyle('base.css');
    const detailStyles = readStyle('detail.css');
    const indexHtml = readFileSync(resolve(currentDir, '../../index.html'), 'utf8');

    expect(indexHtml).toContain('viewport-fit=cover');
    expect(baseStyles).toContain('.agents-shell::before');
    expect(baseStyles).toContain('var(--maverick-shell-mobile-content-top-offset, 0px) +');
    expect(baseStyles).toContain('max(2.15rem, calc(env(safe-area-inset-top, 0px) + 1.15rem))');
    expect(baseStyles).toContain('pointer-events: none;');
    expect(detailStyles).toContain('padding-top: calc(var(--maverick-shell-mobile-content-top-offset, 0px) + env(safe-area-inset-top, 0px) + 28px);');
    expect(detailStyles).toContain('padding: calc(var(--maverick-shell-mobile-content-top-offset, 0px) + env(safe-area-inset-top, 0px) + 18px) 18px calc(env(safe-area-inset-bottom, 0px) + 5.25rem);');
  });
});
