import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string) {
  return readFileSync(resolve(currentDir, filename), 'utf8');
}

describe('skills app scrollbars', () => {
  it('hides the general app scrollbars without disabling content scroll', () => {
    const baseStyles = readStyle('base.css');
    const detailStyles = readStyle('detail.css');

    expect(baseStyles).toMatch(/body\s*\{[^}]*scrollbar-width: none;/);
    expect(baseStyles).toContain('body::-webkit-scrollbar');
    expect(detailStyles).toMatch(/\.skills-detail\s*\{[^}]*overflow: auto;[^}]*scrollbar-width: none;/);
    expect(detailStyles).toContain('.skills-detail::-webkit-scrollbar');
  });
});
