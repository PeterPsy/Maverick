import type { ExecutionFamilyDefinition, ExecutionFamilyId } from './adminApi';

export const EXECUTION_FAMILY_CATALOG: readonly ExecutionFamilyDefinition[] = [
  {
    family_id: 'native_agent',
    label: 'Native Agents (CLI)',
    description: 'External coding-agent runtimes such as Codex, Claude Code, and Gemini CLI. They use their own agent loop and tools, while Maverick launches, connects to, and supervises them.',
    workspace_actions: true
  },
  {
    family_id: 'maverick_agent',
    label: 'Maverick Agents (API)',
    description: 'API models made agentic by Maverick. Maverick provides workspace context, tools, the execution loop, approvals, finalization, and recovery.',
    workspace_actions: true
  },
  {
    family_id: 'hosted_text',
    label: 'Text-only Models (API)',
    description: 'API models without workspace tools or an action loop. They generate text from the context provided by Maverick but cannot perform workspace actions.',
    workspace_actions: false
  }
] as const;

export const NO_WORKSPACE_ACTIONS_MESSAGE = 'No workspace tools or actions.';

export function executionFamily(
  familyId: ExecutionFamilyId,
  projected: ExecutionFamilyDefinition[] | undefined
): ExecutionFamilyDefinition {
  return projected?.find((item) => item.family_id === familyId)
    || EXECUTION_FAMILY_CATALOG.find((item) => item.family_id === familyId)!;
}
