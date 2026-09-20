import type { ExecutionFamilyId, ExecutionFamilyItem, ProviderItem } from "../api/client";

export const EXECUTION_FAMILY_CATALOG: readonly ExecutionFamilyItem[] = [
  {
    family_id: "native_agent",
    label: "CLI models",
    description: "Models running through native command-line agents.",
    workspace_actions: true,
  },
  {
    family_id: "maverick_agent",
    label: "API models",
    description: "Models running through Maverick's agentic API loop.",
    workspace_actions: true,
  },
] as const;

export function orderedExecutionFamilies(providers: ProviderItem[]): ExecutionFamilyItem[] {
  const visibleFamilies = new Set(providers.map(safeProviderExecutionFamily).filter(Boolean));
  return EXECUTION_FAMILY_CATALOG.filter((family) => visibleFamilies.has(family.family_id)).map((fallback, index) => {
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
  return null;
}
