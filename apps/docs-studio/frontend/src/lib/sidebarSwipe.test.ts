import { describe, expect, it } from 'vitest';
import { shouldCloseSidebarFromSwipe } from './sidebarSwipe';

describe('sidebar swipe close gesture', () => {
  it('closes only for a mostly horizontal left swipe', () => {
    expect(shouldCloseSidebarFromSwipe({ x: 180, y: 100 }, { x: 90, y: 112 })).toBe(true);
    expect(shouldCloseSidebarFromSwipe({ x: 180, y: 100 }, { x: 90, y: 170 })).toBe(false);
    expect(shouldCloseSidebarFromSwipe({ x: 90, y: 100 }, { x: 180, y: 112 })).toBe(false);
  });
});
