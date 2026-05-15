import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('storage full preview loading state', () => {
  it('uses the file icon skeleton instead of loading copy while modal content is pending', () => {
    const appSource = readSource('main.tsx');
    const previewSource = readSource('filePreview.tsx');
    const styles = readSource('styles/main.css');

    expect(appSource).toContain('setPreviewLoading(canInlinePreview(file))');
    expect(previewSource).toContain('if (loading) return <FileTypeFallback file={file} loading />;');
    expect(previewSource).not.toContain('Loading preview...');
    expect(previewSource).not.toContain('Loading table preview...');
    expect(styles).toContain('.file-type-card-preview.is-loading-preview > .relative');
  });
});
