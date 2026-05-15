import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string): string {
  return readFileSync(resolve(currentDir, filename), 'utf8');
}

describe('storage file preview widget styles', () => {
  it('uses neutral chat-style chrome instead of red gradient accents', () => {
    const styles = readStyle('styles.css');

    expect(styles).not.toMatch(/gradient/i);
    expect(styles).not.toContain('#d72451');
    expect(styles).not.toContain('#f84b78');
    expect(styles).not.toContain('215, 36, 81');
  });

  it('keeps the document surface tall enough for previews', () => {
    const styles = readStyle('styles.css');

    expect(styles).toContain('--widget-max-document-height: min(60rem, 76dvh);');
    expect(styles).toContain('min-height: 14rem;');
  });
});
