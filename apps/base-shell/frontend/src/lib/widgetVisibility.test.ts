import { describe, expect, it } from 'vitest';
import { widgetVisible } from './widgetVisibility';

describe('widget visibility', () => {
  it('suspends inactive owners, closed sidebars, hidden pages and collapsed overlays', () => {
    for (const active of [false, true]) {
      for (const pageVisible of [false, true]) {
        for (const collapsed of [false, true]) {
          expect(widgetVisible(active, pageVisible, collapsed)).toBe(active && pageVisible && !collapsed);
        }
      }
    }
  });
});
