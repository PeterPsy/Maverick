import { describe, expect, it } from 'vitest';
import { collapsedSectionsWithPageVisible, sectionIdForPageId } from './sidebarSelection';

const sections = [
  { id: 'start-here', pages: [{ id: 'core-overview' }] },
  { id: 'providers', pages: [{ id: 'provider-credentials' }] }
];

describe('sidebar selection state', () => {
  it('finds the section that owns a page id', () => {
    expect(sectionIdForPageId(sections, 'provider-credentials')).toBe('providers');
  });

  it('opens the selected page section without mutating the existing set', () => {
    const collapsed = new Set(['providers', 'sdk']);
    const next = collapsedSectionsWithPageVisible(collapsed, sections, 'provider-credentials');

    expect([...collapsed].sort()).toEqual(['providers', 'sdk']);
    expect([...next].sort()).toEqual(['sdk']);
  });
});
