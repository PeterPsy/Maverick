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
    const source = readStyle('main.tsx');

    expect(styles).toContain('min-height: 20rem;');
    expect(source).toContain('const WIDGET_MAX_HEIGHT_PX = 520;');
    expect(styles).not.toContain('dvh');
  });

  it('keeps iframe scrolling hidden and exposes a transient document scrollbar', () => {
    const styles = readStyle('styles.css');

    expect(styles).toMatch(/html,[\s\S]*body,[\s\S]*#storage-file-preview-root\s*{[\s\S]*overflow:\s*hidden;/);
    expect(styles).toContain('scrollbar-width: none;');
    expect(styles).toContain('.file-widget__document.is-scrolling');
    expect(styles).toContain('.file-widget__document.is-scrolling::-webkit-scrollbar-thumb');
  });

  it('keeps open-in-storage on the title action instead of the whole document', () => {
    const source = readStyle('main.tsx');

    expect(source).toContain('className="file-widget__bar"');
    expect(source).toContain('className="file-widget__open"');
    expect(source).not.toContain('role="button"');
    expect(source).not.toContain('handleDocumentClick');
  });
});
