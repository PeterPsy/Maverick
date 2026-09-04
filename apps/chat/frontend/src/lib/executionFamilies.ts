import type { ExecutionFamilyId, ExecutionFamilyItem, ProviderItem } from "../api/client";

export const EXECUTION_FAMILY_CATALOG: readonly ExecutionFamilyItem[] = [
  {
    family_id: "native_agent",
    label: "Native Agents (CLI)",
    description: "External coding-agent runtimes such as Codex, Claude Code, and Gemini CLI. They use their own agent loop and tools, while Maverick launches, connects to, and supervises them.",
    workspace_actions: true,
  },
  {
    family_id: "maverick_agent",
    label: "Maverick Agents (API)",
    description: "API models made agentic by Maverick. Maverick provides workspace context, tools, the execution loop, approvals, finalization, and recovery.",
    workspace_actions: true,
  },
  {
    family_id: "hosted_text",
    label: "Text-only Models (API)",
    description: "API models without workspace tools or an action loop. They generate text from the context provided by Maverick but cannot perform workspace actions.",
    workspace_actions: false,
  },
] as const;

export const NO_WORKSPACE_ACTIONS_MESSAGE = "No workspace tools or actions.";

export function orderedExecutionFamilies(providers: ProviderItem[]): ExecutionFamilyItem[] {
  return EXECUTION_FAMILY_CATALOG.map((fallback, index) => {
    const projected = providers.find(
      (provider) => provider.execution_family === fallback.family_id,
    );
    return {
      family_id: fallback.family_id,
      label: projected?.execution_family_label || fallback.label,
      description: projected?.execution_family_description || fallback.description,
      workspace_actions: fallback.workspace_actions,
      order: projected?.execution_family_order ?? index,
    } as ExecutionFamilyItem & { order: number };
  }).sort(
    (left, right) =>
      (left as ExecutionFamilyItem & { order: number }).order
      - (right as ExecutionFamilyItem & { order: number }).order,
  );
}

export function safeProviderExecutionFamily(provider: ProviderItem): ExecutionFamilyId | null {
  if (provider.execution_family) {
    return provider.execution_family;
  }
  if (
    provider.provider_id === "codex"
    && provider.provider_role === "runtime_engine"
    && provider.kind === "runtime_backend"
  ) {
    return "native_agent";
  }
  if (
    provider.hosted_provider_id
    || (provider.provider_role === "model_provider" && provider.kind === "hosted_api")
  ) {
    return "hosted_text";
  }
  return null;
}
