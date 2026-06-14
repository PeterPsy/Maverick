import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('exercise media picker UI', () => {
  it('keeps Storage selection as the only media-picking flow', () => {
    const source = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');

    expect(source).toContain('Select video');
    expect(source).toContain('Change video');
    expect(source).toContain('openStorageVideoPicker(media, sourceFolder)');
    expect(source).not.toContain('<span>Clear</span>');
    expect(source).not.toContain('Load Storage');
    expect(source).not.toContain('Drive ref');
    expect(source).not.toContain('Filter Storage media');
  });
});
