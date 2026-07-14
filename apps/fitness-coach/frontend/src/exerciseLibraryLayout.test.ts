import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('exercise library layout styles', () => {
  it('keeps exercise media, details, and actions in non-overlapping mobile grid areas', () => {
    const styles = readFileSync(new URL('./styles.css', import.meta.url), 'utf8');

    expect(styles).toMatch(/@media \(max-width: 920px\)[\s\S]*\.exercise-row\s*{/);
    expect(styles).toContain('grid-template-columns: 5rem minmax(0, 1fr);');
    expect(styles).toContain(`grid-template-areas:
      "media details"
      "actions actions";`);
    expect(styles).toMatch(/\.exercise-preview-button\s*{[\s\S]*grid-area:\s*media;/);
    expect(styles).toMatch(/\.exercise-main\s*{[\s\S]*grid-area:\s*details;/);
    expect(styles).toMatch(/\.exercise-actions\s*{[\s\S]*grid-area:\s*actions;/);
  });
});
