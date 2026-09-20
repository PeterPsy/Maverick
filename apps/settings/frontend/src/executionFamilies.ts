import type { ExecutionFamilyDefinition, ExecutionFamilyId } from './adminApi';

export const EXECUTION_FAMILY_CATALOG: readonly ExecutionFamilyDefinition[] = [
  {
    family_id: 'native_agent',
    label: 'CLI models',
    description: 'Models running through an installed CLI.',
    workspace_actions: true
  },
  {
    family_id: 'maverick_agent',
    label: 'API models',
    description: 'Models running through a provider API.',
    workspace_actions: true
  }
] as const;

export function executionFamily(
  familyId: ExecutionFamilyId,
  projected: ExecutionFamilyDefinition[] | undefined
): ExecutionFamilyDefinition {
  return projected?.find((item) => item.family_id === familyId)
    || EXECUTION_FAMILY_CATALOG.find((item) => item.family_id === familyId)!;
}
