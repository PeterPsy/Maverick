import { describe, expect, it } from 'vitest';
import { hasUnsavedSkillEdits, skillDraftFromDetail } from './SkillsDetail';
import type { SkillDetail } from '../types';

const skill: SkillDetail = {
  id: 'skill-a',
  local_id: 'skill-a',
  name: 'Skill A',
  description: 'Original description.',
  content: 'Original instructions.',
  markdown: '---\nname: Skill A\n---\n\nOriginal instructions.',
  enabled: true,
  created_at: '2026-05-01T00:00:00+00:00',
  updated_at: '2026-05-01T00:00:00+00:00',
  origin: 'workspace',
  source_path: '',
  editable: true,
  deletable: true
};

describe('Skills detail draft state', () => {
  it('detects unsaved edits before applying refreshed skill details', () => {
    const draft = { ...skillDraftFromDetail(skill), content: 'Unsaved local instructions.' };

    expect(hasUnsavedSkillEdits(draft, skill)).toBe(true);
    expect(hasUnsavedSkillEdits(skillDraftFromDetail(skill), skill)).toBe(false);
  });
});
