import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('Storage custom view UI', () => {
  it('tracks custom views in the breadcrumb and uses count-row pills', () => {
    const source = readSource('main.tsx');
    const styles = readSource('styles/main.css');

    expect(source).toContain('<BreadcrumbPage>Custom view</BreadcrumbPage>');
    expect(source).toContain('className="content-count-title"');
    expect(source).not.toContain('custom-view-bar');
    expect(styles).toContain('.content-count-title');
    expect(styles).not.toContain('.custom-view-bar');
  });
});
