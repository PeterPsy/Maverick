import { describe, expect, it } from 'vitest';
import { defaultLocalSkillId, isValidLocalSkillId } from './SkillsExplore';

describe('Skills discovery install ids', () => {
  it('uses a valid remote slug as the local workspace id', () => {
    expect(defaultLocalSkillId('AST Code Analysis')).toBe('ast-code-analysis');
    expect(defaultLocalSkillId('review-helper')).toBe('review-helper');
  });

  it('rejects ids outside the workspace skill contract', () => {
    expect(isValidLocalSkillId('review-helper')).toBe(true);
    expect(isValidLocalSkillId('../review-helper')).toBe(false);
    expect(isValidLocalSkillId('A')).toBe(false);
  });
});
