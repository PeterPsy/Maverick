import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('storage Drive file cards', () => {
  it('does not request automatic asset previews for file cards', () => {
    const source = readSource('filePreview.tsx');
    const functionStart = source.indexOf('function canCardAssetPreview');
    const functionEnd = source.indexOf('function fileCardFormatForFile');
    expect(functionStart).toBeGreaterThanOrEqual(0);
    expect(functionEnd).toBeGreaterThan(functionStart);

    const body = source.slice(functionStart, functionEnd);
    expect(body).toContain('eager backend previews can fan out during navigation');
    expect(body).toContain('return false;');
  });

  it('limits automatic card preview fan-out', () => {
    const source = readSource('previewCache.ts');

    expect(source).toContain('const CARD_PREVIEW_CONCURRENCY = 2;');
    expect(source).toContain('function scheduleCardPreview');
    expect(source).toContain('cardPreviewQueue.push(run);');
    expect(source).toContain("return remember(key, scheduleCardPreview(() => {");
  });
});
