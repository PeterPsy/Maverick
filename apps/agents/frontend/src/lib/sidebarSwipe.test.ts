import { describe, expect, it } from 'vitest';
import { isHorizontalIntent, isSidebarCloseSwipe } from './sidebarSwipe';

describe('Agents sidebar swipe gestures', () => {
  it('recognizes a right-to-left close swipe', () => {
    expect(isSidebarCloseSwipe({ x: 280, y: 220 }, { x: 190, y: 230 })).toBe(true);
  });

  it('rejects short or mostly vertical gestures', () => {
    expect(isSidebarCloseSwipe({ x: 280, y: 220 }, { x: 230, y: 224 })).toBe(false);
    expect(isSidebarCloseSwipe({ x: 280, y: 220 }, { x: 190, y: 290 })).toBe(false);
  });

  it('detects horizontal intent before closing', () => {
    expect(isHorizontalIntent({ x: 280, y: 220 }, { x: 260, y: 222 })).toBe(true);
    expect(isHorizontalIntent({ x: 280, y: 220 }, { x: 276, y: 248 })).toBe(false);
  });
});
