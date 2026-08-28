import type { ProviderItem } from "../api/client";
import { providerUsesPlainHostedRuntime } from "./providerRuntimeOptions";

export function skillIdsVisibleInComposer({
  activationMode,
  allowedSkillIds,
  availableSkillIds,
  provider,
}: {
  activationMode?: string;
  allowedSkillIds?: string[];
  availableSkillIds: string[];
  provider: ProviderItem | null;
}): string[] {
  if (
    activationMode !== "explicit"
    || !provider
    || providerUsesPlainHostedRuntime(provider)
    || (
      provider.provider_role === "runtime_engine"
        ? provider.agentic_effective_capabilities?.capabilities.skill_catalog !== true
        : provider.capabilities?.supports_skills !== true
    )
  ) {
    return [];
  }
  if (!allowedSkillIds?.length) {
    return availableSkillIds;
  }
  const allowed = new Set(allowedSkillIds);
  return availableSkillIds.filter((skillId) => allowed.has(skillId));
}
