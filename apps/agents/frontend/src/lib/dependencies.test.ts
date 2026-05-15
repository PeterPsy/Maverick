import { describe, expect, it } from 'vitest';
import { effectiveSkillIds, normalizeSelectedSkillIds, selectedProviderAppId, skillIdsForAgentSave } from './dependencies';
import type { AgentType, AppDependenciesPayload, SkillSummary } from '../types';

const skills: SkillSummary[] = [
  { id: 'agents-ops', name: 'Agents Ops', description: '', enabled: true },
  { id: 'skills-ops', name: 'Skills Ops', description: '', enabled: true }
];

function agentType(skillIds: string[]): AgentType {
  return {
    id: 'agent-type-test',
    name: 'Test',
    description: '',
    role_id: 'test',
    skill_ids: skillIds,
    trace_verbosity: 'compact',
    enabled: true
  };
}

describe('agents dependency helpers', () => {
  it('resolves the selected runtime skills provider by alias', () => {
    const dependencies: AppDependenciesPayload = {
      workspace_id: 'default',
      consumer_app_id: 'agents',
      status: 'resolved',
      dependencies: [
        {
          alias: 'runtime-skills',
          interface: 'skill.catalog',
          version: '^1',
          required: true,
          cardinality: 'one',
          description: '',
          status: 'resolved',
          candidates: [],
          selected_provider_app_ids: ['workspace-skills'],
          stale_provider_app_ids: [],
          blocked_reason: null
        }
      ]
    };

    expect(selectedProviderAppId(dependencies)).toBe('workspace-skills');
  });

  it('treats an empty agent skill list as all linked workspace skills', () => {
    expect(effectiveSkillIds(agentType([]), skills)).toEqual(['agents-ops', 'skills-ops']);
  });

  it('drops stale skill ids before saving agent edits', () => {
    expect(normalizeSelectedSkillIds(['missing-skill', 'agents-ops', 'agents-ops'], skills)).toEqual(['agents-ops']);
  });

  it('does not broaden an all-stale explicit skill list to every current skill', () => {
    const selection = skillIdsForAgentSave(agentType(['missing-skill']), [], skills);

    expect(effectiveSkillIds(agentType(['missing-skill']), skills)).toEqual([]);
    expect(selection.changed).toBe(false);
    expect(selection.skillIds).toEqual(['missing-skill']);
  });

  it('replaces stale explicit skill ids when the user selects a current skill', () => {
    const selection = skillIdsForAgentSave(agentType(['missing-skill']), ['agents-ops'], skills);

    expect(selection.changed).toBe(true);
    expect(selection.skillIds).toEqual(['agents-ops']);
  });
});
