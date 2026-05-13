export function scalarString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

export function skillIdFromParams(params: Record<string, unknown>) {
  const directSkillId = scalarString(params.skill_id);
  if (directSkillId) {
    return directSkillId;
  }
  const appPage = scalarString(params.app_page);
  const match = appPage.match(/^skills\/([^/?#]+)$/);
  return match?.[1] || '';
}

export function shouldCreateNewSkill(params: Record<string, unknown>) {
  return params.new_skill === true || scalarString(params.new_skill) === 'true';
}
