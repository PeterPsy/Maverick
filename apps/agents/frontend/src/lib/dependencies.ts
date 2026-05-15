import type { AgentType, AppDependenciesPayload, SkillSummary } from '../types';

export const RUNTIME_SKILLS_ALIAS = 'runtime-skills';

export function selectedProviderAppId(
  dependencies: AppDependenciesPayload | null,
  alias = RUNTIME_SKILLS_ALIAS
) {
  const item = dependencies?.dependencies.find((dependency) => dependency.alias === alias);
  return item?.selected_provider_app_ids[0] || '';
}

export function normalizeSelectedSkillIds(skillIds: string[], skills: SkillSummary[]) {
  const available = new Set(skills.map((skill) => skill.id));
  const selected: string[] = [];
  for (const skillId of skillIds) {
    if (!available.has(skillId) || selected.includes(skillId)) {
      continue;
    }
    selected.push(skillId);
  }
  return selected;
}

export function effectiveSkillIds(agentType: AgentType, skills: SkillSummary[]) {
  const explicit = normalizeSelectedSkillIds(agentType.skill_ids, skills);
  return agentType.skill_ids.length ? explicit : skills.map((skill) => skill.id);
}

export function skillIdsForAgentSave(
  agentType: AgentType,
  selectedSkillIds: string[],
  skills: SkillSummary[]
) {
  const normalizedSelected = normalizeSelectedSkillIds(selectedSkillIds, skills);
  const initialSkillIds = effectiveSkillIds(agentType, skills);
  const changed = !sameSet(normalizedSelected, initialSkillIds);
  return {
    changed,
    skillIds: changed ? normalizedSelected : agentType.skill_ids
  };
}

function sameSet(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((item) => rightSet.has(item));
}
