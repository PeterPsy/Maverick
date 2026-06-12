import { describe, expect, it } from 'vitest';
import { moveItemToIndex } from './useWorkoutBlockReorder';

describe('moveItemToIndex', () => {
  it('moves an item to the requested index without mutating the original list', () => {
    const items = ['warmup', 'squat', 'rest', 'pushup'];

    expect(moveItemToIndex(items, 1, 3)).toEqual(['warmup', 'rest', 'pushup', 'squat']);
    expect(items).toEqual(['warmup', 'squat', 'rest', 'pushup']);
  });

  it('clamps target indexes and ignores invalid sources', () => {
    expect(moveItemToIndex(['a', 'b', 'c'], 2, -4)).toEqual(['c', 'a', 'b']);
    expect(moveItemToIndex(['a', 'b', 'c'], 0, 99)).toEqual(['b', 'c', 'a']);
    expect(moveItemToIndex(['a', 'b', 'c'], 99, 0)).toEqual(['a', 'b', 'c']);
  });
});
