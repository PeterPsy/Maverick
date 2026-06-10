import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('Storage picker UI placement', () => {
  it('keeps the Fitness Coach picker action inside the file preview only', () => {
    const source = readFileSync(new URL('./main.tsx', import.meta.url), 'utf8');

    expect(source).toContain('storage-picker-preview-action');
    expect(source).toContain('closePreviewModal();');
    expect(source).not.toContain('storage-picker-action');
    expect(source).not.toContain('details-dialog-actions');
    expect(source.match(/Use video/g) || []).toHaveLength(1);
  });
});
